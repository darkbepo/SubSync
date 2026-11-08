//go:build windows

package main

// Self-check, run on every start (well under a second): every file SubSync
// installed must still be there with the right size.  Anything missing or
// damaged is marked for re-download, so only that piece is fetched again.

import (
	"encoding/csv"
	"io"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

type expectFile struct {
	path string
	size int64 // -1 = only has to exist
}

func pythonOK() bool {
	if !fileExists(filepath.Join(pyDir(), "pythonw.exe")) && !fileExists(filepath.Join(pyDir(), "python.exe")) {
		return false
	}
	pth, _ := filepath.Glob(filepath.Join(pyDir(), "python3*._pth"))
	dll, _ := filepath.Glob(filepath.Join(pyDir(), "python3??.dll"))
	return len(pth) > 0 && len(dll) > 0
}

// wheelTarget maps a path inside a wheel to where installWheel put it ("" = not installed).
func wheelTarget(name string) string {
	parts := strings.SplitN(name, "/", 3)
	if strings.HasSuffix(parts[0], ".data") && len(parts) == 3 {
		switch parts[1] {
		case "purelib", "platlib":
			return filepath.Join(sitePkg(), filepath.FromSlash(parts[2]))
		case "data":
			rel := parts[2]
			if strings.HasPrefix(rel, "Scripts/") {
				if !strings.HasSuffix(strings.ToLower(rel), ".dll") {
					return ""
				}
				rel = strings.TrimPrefix(rel, "Scripts/")
			}
			return filepath.Join(pyDir(), filepath.FromSlash(rel))
		default:
			return ""
		}
	}
	return filepath.Join(sitePkg(), filepath.FromSlash(name))
}

// wheelFiles lists a library's files from its own RECORD (path + size).
func wheelFiles(wheelURL string) ([]expectFile, bool) {
	fn := path.Base(wheelURL)
	f := strings.SplitN(strings.TrimSuffix(fn, ".whl"), "-", 3)
	if len(f) < 2 {
		return nil, false
	}
	distInfo := f[0] + "-" + f[1] + ".dist-info"
	rf, err := os.Open(filepath.Join(sitePkg(), distInfo, "RECORD"))
	if err != nil {
		return nil, false
	}
	defer rf.Close()
	r := csv.NewReader(rf)
	r.FieldsPerRecord = -1
	var out []expectFile
	for {
		rec, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil || len(rec) < 1 || rec[0] == "" {
			continue
		}
		target := wheelTarget(rec[0])
		if target == "" || strings.HasSuffix(rec[0], "/RECORD") || strings.Contains(rec[0], "__pycache__") {
			continue
		}
		size := int64(-1)
		if len(rec) >= 3 && rec[2] != "" {
			if n, err := strconv.ParseInt(rec[2], 10, 64); err == nil {
				size = n
			}
		}
		out = append(out, expectFile{target, size})
	}
	return out, true
}

func modelOK(md item, lk *modelLock) bool {
	dest := filepath.Join(root, filepath.FromSlash(md.Dest))
	if lk != nil && len(lk.Files) > 0 {
		for name, f := range lk.Files {
			if !sizeOK(filepath.Join(dest, name), f.Size) {
				return false
			}
		}
		return true
	}
	// installed by an older version (no lock yet): the expected files must exist
	if len(md.Candidates) == 0 {
		return false
	}
	for _, spec := range md.Candidates[0].Files {
		name := spec
		if i := strings.Index(spec, "="); i >= 0 {
			name = spec[i+1:]
		}
		matches, _ := filepath.Glob(filepath.Join(dest, path.Base(name)))
		ok := false
		for _, mt := range matches {
			if fi, err := os.Stat(mt); err == nil && fi.Size() > 0 {
				ok = true
			}
		}
		if !ok {
			return false
		}
	}
	return true
}

// allPresent checks many files in parallel.
func allPresent(files []expectFile) bool {
	if len(files) == 0 {
		return true
	}
	var bad sync.Once
	broken := false
	jobs := make(chan expectFile, 256)
	var wg sync.WaitGroup
	for w := 0; w < 8; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for f := range jobs {
				fi, err := os.Stat(f.path)
				if err != nil || fi.IsDir() || (f.size >= 0 && fi.Size() != f.size) {
					bad.Do(func() { broken = true })
				}
			}
		}()
	}
	for _, f := range files {
		jobs <- f
	}
	close(jobs)
	wg.Wait()
	return !broken
}

// selfCheck marks every damaged component as not installed and returns a
// readable list of what was wrong.
func selfCheck(m *manifest, gpu bool) []string {
	var problems []string
	if isDone(pyKey(m)) && !pythonOK() {
		unmark(pyKey(m))
		problems = append(problems, "Python runtime")
	}
	for _, w := range m.Wheels {
		key := wheelKey(w.Name)
		if !isDone(key) {
			continue
		}
		files, ok := wheelFiles(w.URL)
		if !ok || !allPresent(files) {
			unmark(key)
			problems = append(problems, "library "+strings.Fields(w.Name)[0])
		}
	}
	if gpu {
		for _, c := range m.Cuda {
			key := "cuda:" + c.Name
			if !isDone(key) {
				continue
			}
			var files []expectFile
			for _, f := range c.Files {
				files = append(files, expectFile{filepath.Join(rt, "cuda", f.Name), f.Size})
			}
			if !allPresent(files) {
				unmark(key)
				problems = append(problems, "GPU library "+strings.Fields(c.Name)[0])
			}
		}
	}
	locks := loadLocks()
	for _, md := range m.Models {
		key := "model:" + md.Dest
		if isDone(key) && !modelOK(md, locks[md.Dest]) {
			unmark(key)
			problems = append(problems, md.Name)
		}
	}
	return problems
}
