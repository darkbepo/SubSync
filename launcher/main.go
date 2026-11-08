//go:build windows

// SubSync.exe – launcher and first-run installer.
//
// Everything is kept in the folder next to this exe:
//
//	runtime\python   embedded Python + libraries
//	runtime\cuda     NVIDIA cuBLAS/cuDNN (only on PCs with an NVIDIA driver)
//	models\          speech + matching AI models
//	app\             SubSync program files (unpacked from this exe)
//	cache\ logs\ settings.json
//
// Deleting the folder removes SubSync completely.
package main

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

//go:embed manifest.json
var manifestJSON []byte

//go:embed all:appfiles
var appFS embed.FS

const userAgent = "SubSync-Setup/1.0"

type item struct {
	Name      string   `json:"name"`
	URL       string   `json:"url"`
	SHA256    string   `json:"sha256"`
	Size      int64    `json:"size"`
	Kind      string   `json:"kind"`
	Dest      string   `json:"dest"`
	Version   string   `json:"version"`
	Fallbacks []string `json:"fallbacks"`
	Files     []struct {
		Name string `json:"name"`
		Size int64  `json:"size"`
	} `json:"files"`
	Candidates []struct {
		Repo  string   `json:"repo"`
		Files []string `json:"files"`
	} `json:"candidates"`
}

type manifest struct {
	Python item   `json:"python"`
	Wheels []item `json:"wheels"`
	Cuda   []item `json:"cuda"`
	Models []item `json:"models"`
}

type installState struct {
	Done map[string]bool `json:"done"`
	App  string          `json:"app"`
}

type task struct {
	key    string // state key
	label  string
	urls   []string                       // tried in order
	more   func(context.Context) []string // looked up only if all urls fail
	sha256 string
	size   int64
	file   string // download target
	finish func(file string) error
}

var netIssue atomic.Value // last connection problem while retrying ("" when fine)

var (
	root      string
	rt        string
	statePath string
	stateMu   sync.Mutex
	state     installState
)

// mode is "gui" for SubSync.exe and "cli" for subsync-cli.exe (set at build time).
var mode = "gui"

func initRoot() error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	if p, err := filepath.EvalSymlinks(exe); err == nil {
		exe = p
	}
	root = filepath.Dir(exe)
	rt = filepath.Join(root, "runtime")
	statePath = filepath.Join(rt, "install-state.json")
	return os.MkdirAll(rt, 0o755)
}

func loadManifest() *manifest {
	var m manifest
	if err := json.Unmarshal(manifestJSON, &m); err != nil {
		fatal("Broken manifest: " + err.Error())
	}
	return &m
}

func main() {
	runtime.LockOSThread()
	if err := initRoot(); err != nil {
		if mode == "cli" {
			fmt.Fprintln(os.Stderr, "SubSync cannot write to its folder: "+root)
			os.Exit(exitSetup)
		}
		fatal("SubSync cannot write to its folder:\n" + root + "\n\nMove SubSync.exe to a folder you own (e.g. Documents\\SubSync).")
	}
	if mode == "cli" {
		os.Exit(cliMain(os.Args[1:]))
	}
	// one window per folder: a second start just brings the open window forward
	if !namedMutex("GUI") {
		focusExisting()
		return
	}
	// is any other SubSync (window or command line) using this folder?
	alone := namedMutex("Any")
	if alone {
		// leftovers from an older version or a crash would lock files and the GPU
		killStrays(root)
	}
	loadState()
	loadSources()
	m := loadManifest()
	gpu := hasNvidiaDriver()
	if needsInstall(m, gpu) {
		if !alone {
			fatal("Some SubSync files need to be repaired, but the command-line version is using this folder right now.\n\nWait for it to finish, then start SubSync again.")
		}
		if len(lastProblems) > 0 || isDone(pyKey(m)) {
			setupTitle = "Repairing SubSync"
			setupSubtitle = "Some files were missing or damaged · downloading only those"
			if len(lastProblems) > 0 {
				logLine("self-check: re-downloading " + strings.Join(lastProblems, ", "))
			}
		}
		if !runInstaller(m, gpu) {
			return
		}
	}
	if err := syncAppFiles(); err != nil {
		fatal("Could not unpack program files: " + err.Error())
	}
	launch()
}

// appEnv is the environment the Python side runs with: everything inside the tool folder.
func appEnv(extra ...string) []string {
	cache := filepath.Join(root, "cache")
	tmp := filepath.Join(cache, "tmp")
	_ = os.MkdirAll(tmp, 0o755)
	env := []string{}
	for _, e := range os.Environ() {
		k := strings.ToUpper(strings.SplitN(e, "=", 2)[0])
		if k == "PYTHONHOME" || k == "PYTHONPATH" || k == "PATH" || k == "TMP" || k == "TEMP" {
			continue
		}
		env = append(env, e)
	}
	env = append(env,
		"SUBSYNC_ROOT="+root,
		"PYTHONNOUSERSITE=1",
		"PATH="+filepath.Join(rt, "cuda")+";"+pyDir()+";"+os.Getenv("PATH"),
		"TMP="+tmp, "TEMP="+tmp,
		"HF_HOME="+filepath.Join(cache, "hf"),
		"CUDA_CACHE_PATH="+filepath.Join(cache, "cuda"),
	)
	return append(env, extra...)
}

var (
	setupTitle    = "Setting up SubSync"
	setupSubtitle = "One-time download · everything stays in this folder"
)

// logLine appends a line to logs\setup.log.
func logLine(msg string) {
	logs := filepath.Join(root, "logs")
	_ = os.MkdirAll(logs, 0o755)
	f, err := os.OpenFile(filepath.Join(logs, "setup.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	fmt.Fprintf(f, "%s %s\n", time.Now().Format("2006-01-02 15:04:05"), msg)
}

func fatal(msg string) {
	messageBox(0, msg, "SubSync", mbOK|mbIconError)
	os.Exit(1)
}

// ---------------------------------------------------------------- state
func loadState() {
	state = installState{Done: map[string]bool{}}
	if b, err := os.ReadFile(statePath); err == nil {
		_ = json.Unmarshal(b, &state)
		if state.Done == nil {
			state.Done = map[string]bool{}
		}
	}
}

func markDone(key string) {
	stateMu.Lock()
	defer stateMu.Unlock()
	state.Done[key] = true
	saveStateLocked()
}

func saveStateLocked() {
	b, _ := json.MarshalIndent(state, "", " ")
	tmp := statePath + ".tmp"
	if os.WriteFile(tmp, b, 0o644) == nil {
		_ = os.Rename(tmp, statePath)
	}
}

func unmark(key string) {
	stateMu.Lock()
	defer stateMu.Unlock()
	if state.Done[key] {
		delete(state.Done, key)
		saveStateLocked()
	}
}

func pyKey(m *manifest) string { return "python:" + m.Python.URL }

func isDone(key string) bool {
	stateMu.Lock()
	defer stateMu.Unlock()
	return state.Done[key]
}

func wheelKey(name string) string {
	if strings.HasPrefix(name, "msvc_runtime") {
		return "vcrt2:" + name // v1.0.0 installed an incomplete (mixed-version) runtime set
	}
	return "wheel:" + name
}

func pyDir() string   { return filepath.Join(rt, "python") }
func sitePkg() string { return filepath.Join(pyDir(), "Lib", "site-packages") }

// needsInstall runs the self-check and reports whether anything must be downloaded.
func needsInstall(m *manifest, gpu bool) bool {
	lastProblems = selfCheck(m, gpu)
	if !isDone(pyKey(m)) {
		return true
	}
	for _, w := range m.Wheels {
		if !isDone(wheelKey(w.Name)) {
			return true
		}
	}
	if gpu {
		for _, w := range m.Cuda {
			if !isDone("cuda:" + w.Name) {
				return true
			}
		}
	}
	for _, md := range m.Models {
		if !isDone("model:" + md.Dest) {
			return true
		}
	}
	return false
}

var lastProblems []string

func fileExists(p string) bool { _, err := os.Stat(p); return err == nil }

func dirHasFiles(p string) bool {
	e, err := os.ReadDir(p)
	return err == nil && len(e) > 0
}

// ---------------------------------------------------------------- installer
func runInstaller(m *manifest, gpu bool) bool {
	st := &progressState{step: "Preparing…"}
	var cancel context.CancelFunc
	var ctx context.Context
	var finished atomic.Bool
	start := func() {
		ctx, cancel = context.WithCancel(context.Background())
		go func() {
			err := install(ctx, m, gpu, st)
			if err != nil {
				if ctx.Err() != nil {
					return
				}
				logLine("setup failed: " + err.Error())
				st.mu.Lock()
				st.failed = true
				st.step = "Setup stopped: " + shortErr(err)
				st.detail = "Check your internet connection, then press Retry. Finished downloads are kept."
				st.mu.Unlock()
				return
			}
			logLine("setup complete")
			finished.Store(true)
			st.mu.Lock()
			st.finished = true
			st.mu.Unlock()
		}()
	}
	runInstallWindow(root, st, start, start, func() {
		if cancel != nil {
			cancel()
		}
	})
	return finished.Load()
}

func shortErr(err error) string {
	s := err.Error()
	low := strings.ToLower(s)
	for _, k := range []string{"dial tcp", "no such host", "connection refused", "timeout", "connection reset", "tls", "eof", "proxy", "forbidden"} {
		if strings.Contains(low, k) {
			return "can't reach the download server"
		}
	}
	if strings.Contains(low, "not enough disk space") {
		return s
	}
	if len(s) > 160 {
		s = s[:160] + "…"
	}
	return s
}

type modelGoneError struct {
	dest string
	err  error
}

func (e modelGoneError) Error() string { return "model source gone: " + e.err.Error() }

// install runs the downloads; if a pinned model has vanished from every host,
// the pin is dropped and the model comes from a backup repository instead.
func install(ctx context.Context, m *manifest, gpu bool, st *progressState) error {
	err := installOnce(ctx, m, gpu, st)
	var mg modelGoneError
	for tries := 0; tries < 2 && errors.As(err, &mg); tries++ {
		locks := loadLocks()
		delete(locks, mg.dest)
		saveLocks(locks)
		_ = os.RemoveAll(filepath.Join(root, filepath.FromSlash(mg.dest)))
		unmark("model:" + mg.dest)
		st.set("The original model source is gone – switching to a backup source…", "", -1)
		err = installOnce(ctx, m, gpu, st)
	}
	return err
}

func installOnce(ctx context.Context, m *manifest, gpu bool, st *progressState) error {
	dl := filepath.Join(rt, "downloads")
	if err := os.MkdirAll(dl, 0o755); err != nil {
		return err
	}
	client := &http.Client{Timeout: 0}
	st.set("Checking what needs to be downloaded…", "", 0)

	var tasks []*task
	// Python
	if !isDone(pyKey(m)) || !pythonOK() {
		size := m.Python.Size
		if size == 0 {
			size = headSize(ctx, client, m.Python.URL, 11<<20)
		}
		urls := append(append(append([]string{}, sources.PythonURLs...), m.Python.URL), m.Python.Fallbacks...)
		tasks = append(tasks, &task{key: pyKey(m), label: "Python", urls: urls, sha256: m.Python.SHA256, size: size,
			file: filepath.Join(dl, "python-runtime.zip"), finish: installPython})
		// Python's own files include an older C++ runtime: re-apply the matching set after it
		for _, w := range m.Wheels {
			if strings.HasPrefix(w.Name, "msvc_runtime") {
				unmark(wheelKey(w.Name))
			}
		}
	}
	for _, w := range m.Wheels {
		w := w
		if isDone(wheelKey(w.Name)) {
			continue
		}
		tasks = append(tasks, &task{key: wheelKey(w.Name), label: "Python libraries", urls: []string{w.URL},
			more: func(ctx context.Context) []string {
				return indexLookup(ctx, client, strings.Fields(w.Name)[0], path.Base(w.URL))
			},
			sha256: w.SHA256, size: w.Size, file: filepath.Join(dl, path.Base(w.URL)),
			finish: func(f string) error { return installWheel(f) }})
	}
	if gpu {
		for _, w := range m.Cuda {
			w := w
			if isDone("cuda:" + w.Name) {
				continue
			}
			tasks = append(tasks, &task{key: "cuda:" + w.Name, label: "GPU libraries", urls: []string{w.URL},
				more: func(ctx context.Context) []string {
					return indexLookup(ctx, client, strings.Fields(w.Name)[0], path.Base(w.URL))
				},
				sha256: w.SHA256, size: w.Size, file: filepath.Join(dl, path.Base(w.URL)), finish: installCuda})
		}
	}
	locks := loadLocks()
	for _, md := range m.Models {
		if isDone("model:" + md.Dest) {
			continue
		}
		mt, err := resolveModel(ctx, client, md, dl, locks)
		if err != nil {
			return err
		}
		tasks = append(tasks, mt...)
	}

	var total int64
	for _, t := range tasks {
		total += t.size
	}
	need := uint64(float64(total) * 2.2)
	if free := freeDiskBytes(root); free > 0 && free < need {
		return fmt.Errorf("not enough disk space: %s needed, %s free", humanBytes(int64(need)), humanBytes(int64(free)))
	}
	// big files first so the parallel downloads overlap well
	sort.SliceStable(tasks, func(i, j int) bool { return tasks[i].size > tasks[j].size })

	var done atomic.Int64
	active := &activeSet{n: map[string]int{}}
	stop := make(chan struct{})
	go reporter(st, &done, total, active, stop)
	defer close(stop)

	// Python goes first: its zip contains an older C++ runtime that must not
	// overwrite the complete, newer set installed afterwards.
	var rest []*task
	for _, t := range tasks {
		if !strings.HasPrefix(t.key, "python:") {
			rest = append(rest, t)
			continue
		}
		active.add(t.label, 1)
		err := download(ctx, client, t, &done)
		if err == nil {
			err = t.finish(t.file)
		}
		active.add(t.label, -1)
		if err != nil {
			return fmt.Errorf("%s: %w", t.label, err)
		}
		_ = os.Remove(t.file)
		markDone(t.key)
	}
	tasks = rest

	ictx, icancel := context.WithCancel(ctx) // first hard failure stops the others at once
	defer icancel()
	sem := make(chan struct{}, 3)
	errCh := make(chan error, len(tasks))
	var wg sync.WaitGroup
	var extractMu sync.Mutex // extraction writes into shared folders: one at a time
	for _, t := range tasks {
		t := t
		wg.Add(1)
		go func() {
			defer wg.Done()
			select {
			case sem <- struct{}{}:
			case <-ictx.Done():
				return
			}
			defer func() { <-sem }()
			active.add(t.label, 1)
			defer active.add(t.label, -1)
			if err := download(ictx, client, t, &done); err != nil {
				var nf notFoundError
				if strings.HasPrefix(t.key, "file:") && errors.As(err, &nf) {
					err = modelGoneError{dest: path.Dir(strings.TrimPrefix(t.key, "file:")), err: err}
				}
				if ictx.Err() == nil || ctx.Err() != nil {
					errCh <- fmt.Errorf("%s: %w", t.label, err)
				}
				icancel()
				return
			}
			extractMu.Lock()
			err := t.finish(t.file)
			extractMu.Unlock()
			if err != nil {
				errCh <- fmt.Errorf("%s: %w", t.label, err)
				icancel()
				return
			}
			_ = os.Remove(t.file)
			markDone(t.key)
		}()
	}
	wg.Wait()
	close(errCh)
	if err := <-errCh; err != nil {
		return err
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	// a model is complete only when every locked file is present and the right size
	locks = loadLocks()
	for _, md := range m.Models {
		if modelOK(md, locks[md.Dest]) {
			markDone("model:" + md.Dest)
		}
	}
	st.set("Finishing…", "", 1)
	if err := os.RemoveAll(dl); err != nil {
		_ = err
	}
	if !gpu {
		_ = os.RemoveAll(filepath.Join(rt, "cuda"))
	}
	return nil
}

type activeSet struct {
	mu sync.Mutex
	n  map[string]int
}

func (a *activeSet) add(label string, d int) {
	a.mu.Lock()
	a.n[label] += d
	if a.n[label] <= 0 {
		delete(a.n, label)
	}
	a.mu.Unlock()
}

func (a *activeSet) labels() []string {
	a.mu.Lock()
	defer a.mu.Unlock()
	var out []string
	for k := range a.n {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func reporter(st *progressState, done *atomic.Int64, total int64, active *activeSet, stop chan struct{}) {
	type sample struct {
		t time.Time
		n int64
	}
	var hist []sample
	tk := time.NewTicker(250 * time.Millisecond)
	defer tk.Stop()
	for {
		select {
		case <-stop:
			return
		case <-tk.C:
		}
		n := done.Load()
		now := time.Now()
		hist = append(hist, sample{now, n})
		for len(hist) > 2 && now.Sub(hist[0].t) > 8*time.Second {
			hist = hist[1:]
		}
		speed := 0.0
		if dt := now.Sub(hist[0].t).Seconds(); dt > 0.5 {
			speed = float64(n-hist[0].n) / dt
		}
		labels := active.labels()
		step := "Downloading"
		if len(labels) > 0 {
			step = "Downloading " + joinAnd(labels)
		}
		detail := fmt.Sprintf("%s of %s", humanBytes(n), humanBytes(total))
		if speed > 0 {
			detail += fmt.Sprintf("  ·  %.1f MB/s", speed/(1<<20))
			if left := float64(total-n) / speed; left > 0 {
				if left >= 90 {
					detail += fmt.Sprintf("  ·  about %d min left", int(left/60+0.5))
				} else {
					detail += "  ·  less than 2 min left"
				}
			}
		}
		if v, _ := netIssue.Load().(string); v != "" && speed < 1 {
			detail = v
		}
		frac := 0.0
		if total > 0 {
			frac = float64(n) / float64(total)
		}
		if n >= total && total > 0 {
			step, detail = "Unpacking…", humanBytes(total)+" downloaded"
		}
		st.set(step+"…", detail, frac*0.99)
	}
}

func joinAnd(s []string) string {
	if len(s) <= 1 {
		return strings.Join(s, "")
	}
	return strings.Join(s[:len(s)-1], ", ") + " and " + s[len(s)-1]
}

func uniq(s []string) []string {
	out := s[:0]
	for i, v := range s {
		if i == 0 || v != s[i-1] {
			out = append(out, v)
		}
	}
	return out
}

func headSize(ctx context.Context, c *http.Client, url string, fallback int64) int64 {
	req, _ := http.NewRequestWithContext(ctx, "HEAD", url, nil)
	req.Header.Set("User-Agent", userAgent)
	resp, err := c.Do(req)
	if err != nil {
		return fallback
	}
	resp.Body.Close()
	if resp.ContentLength > 0 {
		return resp.ContentLength
	}
	return fallback
}

type notFoundError struct{ msg string }

func (e notFoundError) Error() string { return e.msg }

// download tries every source of a task in turn (resume + SHA-256 check per source).
func download(ctx context.Context, c *http.Client, t *task, done *atomic.Int64) error {
	tried := map[string]bool{}
	var lastErr error
	anyNotFound := false
	try := func(list []string) (bool, error) {
		for _, u := range list {
			if tried[u] {
				continue
			}
			tried[u] = true
			err := downloadFrom(ctx, c, t, u, done)
			if err == nil {
				return true, nil
			}
			if ctx.Err() != nil {
				return false, ctx.Err()
			}
			var nf notFoundError
			if errors.As(err, &nf) {
				anyNotFound = true
			}
			lastErr = err
			netIssue.Store("That source didn't work – trying another download source…")
		}
		return false, nil
	}
	if ok, err := try(t.urls); ok || err != nil {
		return err
	}
	if t.more != nil {
		if ok, err := try(t.more(ctx)); ok || err != nil {
			return err
		}
	}
	if lastErr == nil {
		return errors.New("no download source available")
	}
	if anyNotFound { // at least one source says the file no longer exists
		return notFoundError{"a source says this file no longer exists: " + lastErr.Error()}
	}
	return lastErr
}

func downloadFrom(ctx context.Context, c *http.Client, t *task, src string, done *atomic.Int64) error {
	part := t.file + ".part"
	if t.sha256 == "" { // without a checksum, partial data from different sources must not be mixed
		h := sha256.Sum256([]byte(src))
		part = t.file + "." + hex.EncodeToString(h[:4]) + ".part"
	}
	var have int64
	if fi, err := os.Stat(part); err == nil {
		have = fi.Size()
	}
	if t.size > 0 && have > t.size {
		_ = os.Remove(part)
		have = 0
	}
	done.Add(have)
	fail := func(err error) error {
		done.Add(-have)
		return err
	}
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if ctx.Err() != nil {
			return fail(ctx.Err())
		}
		if t.size > 0 && have == t.size && t.sha256 != "" {
			lastErr = nil
			break
		}
		req, err := http.NewRequestWithContext(ctx, "GET", src, nil)
		if err != nil {
			return fail(err)
		}
		req.Header.Set("User-Agent", userAgent)
		if have > 0 {
			req.Header.Set("Range", fmt.Sprintf("bytes=%d-", have))
		}
		resp, err := c.Do(req)
		if err != nil {
			lastErr = err
			netIssue.Store(fmt.Sprintf("Connection problem – retrying (%d/3)…", attempt+1))
			time.Sleep(time.Duration(attempt+1) * 2 * time.Second)
			continue
		}
		netIssue.Store("")
		if resp.StatusCode == 416 && have > 0 { // already complete
			resp.Body.Close()
			lastErr = nil
			break
		}
		if have > 0 && resp.StatusCode == 200 { // server ignored Range: start over
			done.Add(-have)
			have = 0
			_ = os.Remove(part)
		}
		if resp.StatusCode != 200 && resp.StatusCode != 206 {
			resp.Body.Close()
			if resp.StatusCode == 404 || resp.StatusCode == 410 || resp.StatusCode == 403 || resp.StatusCode == 401 {
				return fail(notFoundError{fmt.Sprintf("%s answered %s", hostOf(src), resp.Status)})
			}
			lastErr = fmt.Errorf("%s answered %s", hostOf(src), resp.Status)
			time.Sleep(time.Duration(attempt+1) * 2 * time.Second)
			continue
		}
		if t.size == 0 && resp.ContentLength > 0 {
			t.size = have + resp.ContentLength
		}
		f, err := os.OpenFile(part, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		if err != nil {
			resp.Body.Close()
			return fail(err)
		}
		lastErr = nil
		buf := make([]byte, 256<<10)
		for {
			n, rerr := resp.Body.Read(buf)
			if n > 0 {
				if _, werr := f.Write(buf[:n]); werr != nil {
					f.Close()
					resp.Body.Close()
					return fail(werr)
				}
				have += int64(n)
				done.Add(int64(n))
			}
			if rerr == io.EOF {
				break
			}
			if rerr != nil {
				lastErr = rerr
				break
			}
		}
		f.Close()
		resp.Body.Close()
		if lastErr == nil {
			break
		}
		if ctx.Err() != nil {
			return fail(ctx.Err())
		}
		time.Sleep(time.Duration(attempt+1) * 2 * time.Second)
	}
	if lastErr != nil {
		return fail(lastErr)
	}
	if t.sha256 != "" {
		sum, err := fileSHA256(part)
		if err != nil {
			return fail(err)
		}
		if !strings.EqualFold(sum, t.sha256) {
			_ = os.Remove(part)
			return fail(fmt.Errorf("file from %s failed the checksum test", hostOf(src)))
		}
	}
	if err := os.Rename(part, t.file); err != nil {
		return fail(err)
	}
	return nil
}

func hostOf(u string) string {
	if p, err := url.Parse(u); err == nil && p.Host != "" {
		return p.Host
	}
	return u
}

func fileSHA256(p string) (string, error) {
	f, err := os.Open(p)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// ---------------------------------------------------------------- models (Hugging Face)
type hfEntry struct {
	Type string `json:"type"`
	Path string `json:"path"`
	Size int64  `json:"size"`
	LFS  *struct {
		Oid  string `json:"oid"`
		Size int64  `json:"size"`
	} `json:"lfs"`
}

// resolveModel returns download tasks for every missing/damaged model file.
// The first install pins the repository's exact revision in models.lock.json;
// repairs fetch exactly that revision, from any host.
func resolveModel(ctx context.Context, c *http.Client, md item, dl string, locks map[string]*modelLock) ([]*task, error) {
	dest := filepath.Join(root, filepath.FromSlash(md.Dest))
	if lk := locks[md.Dest]; lk != nil && lk.Repo != "" && lk.Revision != "" && len(lk.Files) > 0 {
		return modelTasks(md, dest, dl, lk), nil
	}
	var lastErr error
	for _, cand := range md.Candidates {
		if lk := locks[md.Dest]; lk != nil && lk.Repo != "" && lk.Repo != cand.Repo && lk.Revision != "" {
			continue // locked to another repository
		}
		rev, entries, err := hfResolve(ctx, c, cand.Repo)
		if err != nil {
			lastErr = err
			continue
		}
		files := map[string]lockedFile{}
		ok := true
		for _, spec := range cand.Files {
			src, as := spec, ""
			if i := strings.Index(spec, "="); i >= 0 {
				src, as = spec[:i], spec[i+1:]
			}
			found := false
			for _, e := range entries {
				if e.Type != "file" {
					continue
				}
				if m, _ := path.Match(src, e.Path); !m {
					continue
				}
				found = true
				name := as
				if name == "" {
					name = path.Base(e.Path)
				}
				lf := lockedFile{Path: e.Path, Size: e.Size}
				if e.LFS != nil {
					lf.SHA256 = e.LFS.Oid
					if e.LFS.Size > 0 {
						lf.Size = e.LFS.Size
					}
				}
				files[name] = lf
			}
			if !found {
				ok = false
				break
			}
		}
		if !ok {
			lastErr = fmt.Errorf("model files missing in %s", cand.Repo)
			continue
		}
		lk := &modelLock{Repo: cand.Repo, Revision: rev, Files: files}
		locks[md.Dest] = lk
		saveLocks(locks)
		return modelTasks(md, dest, dl, lk), nil
	}
	return nil, fmt.Errorf("could not find the %s: %v", md.Name, lastErr)
}

func modelTasks(md item, dest, dl string, lk *modelLock) []*task {
	var tasks []*task
	for name, f := range lk.Files {
		name, f := name, f
		final := filepath.Join(dest, name)
		if sizeOK(final, f.Size) {
			continue
		}
		_ = os.Remove(final)
		tasks = append(tasks, &task{key: "file:" + md.Dest + "/" + name, label: md.Name, size: f.Size, sha256: f.SHA256,
			urls: hfURLs(lk.Repo, lk.Revision, f.Path),
			file: filepath.Join(dl, strings.ReplaceAll(md.Dest, "/", "_")+"_"+name),
			finish: func(file string) error {
				if err := os.MkdirAll(dest, 0o755); err != nil {
					return err
				}
				return os.Rename(file, final)
			}})
	}
	return tasks
}

func sizeOK(p string, size int64) bool {
	fi, err := os.Stat(p)
	return err == nil && !fi.IsDir() && (size <= 0 || fi.Size() == size)
}

// ---------------------------------------------------------------- unpacking
func safeJoin(base, name string) (string, error) {
	name = filepath.FromSlash(name)
	if filepath.IsAbs(name) || strings.Contains(name, ":") {
		return "", fmt.Errorf("bad path in archive: %s", name)
	}
	p := filepath.Join(base, name)
	if !strings.HasPrefix(p, filepath.Clean(base)+string(os.PathSeparator)) {
		return "", fmt.Errorf("bad path in archive: %s", name)
	}
	return p, nil
}

func writeZipFile(zf *zip.File, dst string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	r, err := zf.Open()
	if err != nil {
		return err
	}
	defer r.Close()
	f, err := os.Create(dst)
	if err != nil {
		return err
	}
	if _, err := io.Copy(f, r); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

func installPython(file string) error {
	zr, err := zip.OpenReader(file)
	if err != nil {
		return err
	}
	defer zr.Close()
	nuget := false
	for _, zf := range zr.File {
		if strings.EqualFold(zf.Name, "tools/python.exe") {
			nuget = true
			break
		}
	}
	for _, zf := range zr.File {
		if zf.FileInfo().IsDir() {
			continue
		}
		name := zf.Name
		if nuget { // NuGet package: the Python installation is under tools/
			if !strings.HasPrefix(strings.ToLower(name), "tools/") {
				continue
			}
			name = name[len("tools/"):]
		}
		dst, err := safeJoin(pyDir(), name)
		if err != nil {
			return err
		}
		if err := writeZipFile(zf, dst); err != nil {
			return err
		}
	}
	// find the version's ._pth name (python312._pth) from its DLL
	dlls, _ := filepath.Glob(filepath.Join(pyDir(), "python3??.dll"))
	if len(dlls) == 0 {
		dlls, _ = filepath.Glob(filepath.Join(pyDir(), "python3?.dll"))
	}
	if len(dlls) == 0 {
		return errors.New("python DLL not found in the download")
	}
	stem := strings.TrimSuffix(filepath.Base(dlls[0]), ".dll")
	var pth string
	if fileExists(filepath.Join(pyDir(), stem+".zip")) { // embeddable layout
		pth = stem + ".zip\r\n.\r\nLib\\site-packages\r\n..\\..\\app\r\nimport site\r\n"
	} else { // full layout (NuGet)
		pth = "Lib\r\nDLLs\r\n.\r\nLib\\site-packages\r\n..\\..\\app\r\nimport site\r\n"
	}
	if err := os.WriteFile(filepath.Join(pyDir(), stem+"._pth"), []byte(pth), 0o644); err != nil {
		return err
	}
	return os.MkdirAll(sitePkg(), 0o755)
}

func installWheel(file string) error {
	zr, err := zip.OpenReader(file)
	if err != nil {
		return err
	}
	defer zr.Close()
	for _, zf := range zr.File {
		if zf.FileInfo().IsDir() {
			continue
		}
		name := zf.Name
		base := sitePkg()
		parts := strings.SplitN(name, "/", 3)
		if strings.HasSuffix(parts[0], ".data") && len(parts) == 3 {
			switch parts[1] {
			case "purelib", "platlib":
				name = parts[2]
			case "data":
				if strings.HasPrefix(parts[2], "Scripts/") {
					// msvc-runtime keeps vcruntime140*.dll here: python.exe must get the
					// complete set from one version, never a mix
					if !strings.HasSuffix(strings.ToLower(parts[2]), ".dll") {
						continue
					}
					base, name = pyDir(), strings.TrimPrefix(parts[2], "Scripts/")
				} else {
					base, name = pyDir(), parts[2]
				}
			default: // scripts, headers
				continue
			}
		}
		dst, err := safeJoin(base, name)
		if err != nil {
			return err
		}
		if err := writeZipFile(zf, dst); err != nil {
			return err
		}
	}
	return nil
}

func installCuda(file string) error {
	zr, err := zip.OpenReader(file)
	if err != nil {
		return err
	}
	defer zr.Close()
	cuda := filepath.Join(rt, "cuda")
	for _, zf := range zr.File {
		n := zf.Name
		b := path.Base(n)
		if !strings.Contains(n, "/bin/") || !strings.HasSuffix(strings.ToLower(b), ".dll") {
			continue
		}
		if strings.HasPrefix(b, "nvblas") || strings.Contains(b, ".alt.") {
			continue
		}
		if err := writeZipFile(zf, filepath.Join(cuda, b)); err != nil {
			return err
		}
	}
	return nil
}

// ---------------------------------------------------------------- app files + launch
func appVersion() string {
	h := sha256.New()
	_ = fs.WalkDir(appFS, "appfiles", func(p string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() {
			b, _ := appFS.ReadFile(p)
			h.Write([]byte(p))
			h.Write(b)
		}
		return nil
	})
	return hex.EncodeToString(h.Sum(nil))[:16]
}

func syncAppFiles() error {
	v := appVersion()
	appDir := filepath.Join(root, "app")
	intact := state.App == v
	if intact {
		_ = fs.WalkDir(appFS, "appfiles", func(p string, d fs.DirEntry, err error) error {
			if err != nil || d.IsDir() || !intact {
				return nil
			}
			info, _ := d.Info()
			dst := filepath.Join(appDir, filepath.FromSlash(strings.TrimPrefix(p, "appfiles/")))
			if !sizeOK(dst, info.Size()) {
				intact = false
			}
			return nil
		})
	}
	if intact {
		return nil
	}
	_ = os.RemoveAll(appDir)
	err := fs.WalkDir(appFS, "appfiles", func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		rel := strings.TrimPrefix(p, "appfiles/")
		dst := filepath.Join(appDir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return err
		}
		b, err := appFS.ReadFile(p)
		if err != nil {
			return err
		}
		return os.WriteFile(dst, b, 0o644)
	})
	if err != nil {
		return err
	}
	stateMu.Lock()
	state.App = v
	saveStateLocked()
	stateMu.Unlock()
	return nil
}

func launch() {
	logs := filepath.Join(root, "logs")
	_ = os.MkdirAll(logs, 0o755)
	cache := filepath.Join(root, "cache")
	tmp := filepath.Join(cache, "tmp")
	_ = os.MkdirAll(tmp, 0o755)
	errLog, _ := os.Create(filepath.Join(logs, "startup.log"))
	readyFile := filepath.Join(cache, "window-ready.flag")
	_ = os.Remove(readyFile)

	py := filepath.Join(pyDir(), "pythonw.exe")
	noConsole := false
	if !fileExists(py) {
		py, noConsole = filepath.Join(pyDir(), "python.exe"), true
	}
	cmd := exec.Command(py, "-X", "utf8", filepath.Join(root, "app", "main.py"))
	cmd.Dir = root
	env := appEnv("SUBSYNC_READY_FILE=" + readyFile)
	cmd.Env = env
	if errLog != nil {
		cmd.Stdout, cmd.Stderr = errLog, errLog
	}
	// NOTE: no HideWindow here - Windows applies the launcher's "start hidden"
	// flag to the app's first window, which made SubSync open invisibly.
	// pythonw.exe has no console, so nothing needs hiding.
	pAllowSetForegroundWindow.Call(^uintptr(0)) // let the app's window come to the front
	if noConsole {
		cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000} // CREATE_NO_WINDOW
	}
	job := newKillOnCloseJob()
	if err := cmd.Start(); err != nil {
		fatal("Could not start SubSync: " + err.Error())
	}
	// the app and every helper process it starts belong to this job: when this
	// launcher ends - normally, by crash or killed - Windows ends all of them
	assignToJob(job, cmd.Process.Pid)
	exited := make(chan error, 1)
	go func() { exited <- cmd.Wait() }()

	failed := func(reason string) {
		killJob(job)
		if errLog != nil {
			errLog.Close()
		}
		msg := reason
		if t := tail(filepath.Join(logs, "app.log"), 25); t != "" {
			msg += "\n\nEnd of logs\\app.log:\n" + t
		}
		if t := tail(filepath.Join(logs, "startup.log"), 10); t != "" {
			msg += "\n\nlogs\\startup.log:\n" + t
		}
		msg += "\n\nLog folder: " + logs
		fatal(msg)
	}

	// phase 1: wait for the window to appear
	tick := time.NewTicker(200 * time.Millisecond)
	defer tick.Stop()
	slow := time.After(60 * time.Second)
	ready := false
	for !ready {
		select {
		case <-exited:
			if fileExists(readyFile) {
				killJob(job)
				return
			}
			code := uint32(0)
			if cmd.ProcessState != nil {
				code = uint32(cmd.ProcessState.ExitCode())
			}
			failed(fmt.Sprintf("SubSync closed before its window appeared (%s).", exitReason(code)))
		case <-tick.C:
			ready = fileExists(readyFile)
		case <-slow:
			if messageBox(0, "SubSync is taking unusually long to open.\n\nKeep waiting?\n(No closes it and shows what it was doing.)",
				"SubSync", mbYesNo|mbIconWarning) != idYes {
				failed("SubSync did not open within a reasonable time and was closed.")
			}
			slow = time.After(60 * time.Second)
		}
	}
	// phase 2: stay in the background until the app ends, then make sure
	// no helper process outlives it
	<-exited
	code := uint32(0)
	if cmd.ProcessState != nil {
		code = uint32(cmd.ProcessState.ExitCode())
	}
	if code != 0 {
		failed(fmt.Sprintf("SubSync stopped unexpectedly (%s).", exitReason(code)))
	}
	killJob(job)
}

func exitReason(code uint32) string {
	switch code {
	case 0:
		return "it exited normally"
	case 0xC0000005:
		return "crash inside a library: access violation 0xC0000005"
	case 0xC0000409:
		return "fatal error / fail-fast 0xC0000409"
	case 0xC0000135:
		return "a required DLL was not found 0xC0000135"
	case 0xC0000142:
		return "a DLL failed to initialise 0xC0000142"
	case 0xC000001D:
		return "illegal CPU instruction 0xC000001D"
	}
	return fmt.Sprintf("exit code 0x%X", code)
}

func tail(p string, n int) string {
	b, err := os.ReadFile(p)
	if err != nil {
		return ""
	}
	lines := strings.Split(strings.TrimRight(strings.ReplaceAll(string(b), "\r\n", "\n"), "\n"), "\n")
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	out := strings.Join(lines, "\n")
	if len(out) > 2500 {
		out = "…" + out[len(out)-2500:]
	}
	return strings.TrimSpace(out)
}
