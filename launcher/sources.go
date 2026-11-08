//go:build windows

package main

// Where downloads come from, and what to try when a link stops working.
//
//   Python      python.org  ->  official NuGet "python" package
//   libraries   the exact PyPI file link  ->  any PEP 503 package index that has
//               the same file (pypi.org, mirrors, your own) - always checked
//               against the SHA-256 recorded at build time
//   AI models   huggingface.co  ->  hf-mirror.com, at the exact revision that was
//               installed first (models.lock.json); backup repositories if the
//               original repository disappears
//
// A sources.json next to SubSync.exe can add your own locations; they are tried
// first.  Example:
//   { "python_urls":  ["https://my.server/subsync/python-3.12.10-embed-amd64.zip"],
//     "pypi_indexes": ["https://my.server/simple"],
//     "hf_hosts":     ["https://my.server/hf"] }

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type sourceConfig struct {
	PythonURLs  []string `json:"python_urls"`
	PyPIIndexes []string `json:"pypi_indexes"`
	HFHosts     []string `json:"hf_hosts"`
}

var defaultPyPIIndexes = []string{
	"https://pypi.org/simple",
	"https://pypi.tuna.tsinghua.edu.cn/simple",
	"https://mirrors.aliyun.com/pypi/simple",
}

var defaultHFHosts = []string{"https://huggingface.co", "https://hf-mirror.com"}

var sources sourceConfig

func loadSources() {
	var user sourceConfig
	if b, err := os.ReadFile(filepath.Join(root, "sources.json")); err == nil {
		_ = json.Unmarshal(b, &user)
	}
	trim := func(in []string) []string {
		var out []string
		for _, s := range in {
			if s = strings.TrimRight(strings.TrimSpace(s), "/"); s != "" {
				out = append(out, s)
			}
		}
		return out
	}
	sources.PythonURLs = trim(user.PythonURLs)
	sources.PyPIIndexes = append(trim(user.PyPIIndexes), defaultPyPIIndexes...)
	sources.HFHosts = append(trim(user.HFHosts), defaultHFHosts...)
}

var pep503 = regexp.MustCompile(`[-_.]+`)

// indexLookup finds a wheel file by name on PEP 503 "simple" indexes.
// Returns candidate URLs (checked against the SHA-256 when downloaded).
func indexLookup(ctx context.Context, c *http.Client, project, filename string) []string {
	name := strings.ToLower(pep503.ReplaceAllString(project, "-"))
	var out []string
	href := regexp.MustCompile(`href\s*=\s*["']([^"']+)["']`)
	for _, idx := range sources.PyPIIndexes {
		if len(out) >= 2 { // two independent sources are plenty
			break
		}
		page := idx + "/" + name + "/"
		body, err := getSmall(ctx, c, page, 4<<20)
		if err != nil {
			continue
		}
		base, _ := url.Parse(page)
		for _, m := range href.FindAllStringSubmatch(body, -1) {
			u, err := url.Parse(strings.ReplaceAll(m[1], "&amp;", "&"))
			if err != nil {
				continue
			}
			full := base.ResolveReference(u)
			if pathBase(full.Path) == filename {
				full.Fragment = ""
				out = append(out, full.String())
				break
			}
		}
	}
	return out
}

func pathBase(p string) string {
	if i := strings.LastIndex(p, "/"); i >= 0 {
		return p[i+1:]
	}
	return p
}

func getSmall(ctx context.Context, c *http.Client, u string, max int64) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", u, nil)
	req.Header.Set("User-Agent", userAgent)
	resp, err := c.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("%s: %s", u, resp.Status)
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, max))
	return string(b), err
}

func getJSON(ctx context.Context, c *http.Client, u string, v any) error {
	body, err := getSmall(ctx, c, u, 16<<20)
	if err != nil {
		return err
	}
	return json.Unmarshal([]byte(body), v)
}

// ---------------------------------------------------------------- model lock
type lockedFile struct {
	Path   string `json:"path"` // path inside the repository
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256,omitempty"`
}

type modelLock struct {
	Repo     string                `json:"repo"`
	Revision string                `json:"revision"` // exact commit; "" = unknown (installed by an older version)
	Files    map[string]lockedFile `json:"files"`    // local name -> source
}

func lockPath() string { return filepath.Join(rt, "models.lock.json") }

func loadLocks() map[string]*modelLock {
	locks := map[string]*modelLock{}
	if b, err := os.ReadFile(lockPath()); err == nil {
		_ = json.Unmarshal(b, &locks)
	}
	return locks
}

func saveLocks(locks map[string]*modelLock) {
	b, _ := json.MarshalIndent(locks, "", " ")
	tmp := lockPath() + ".tmp"
	if os.WriteFile(tmp, b, 0o644) == nil {
		_ = os.Rename(tmp, lockPath())
	}
}

func hfURLs(repo, rev, file string) []string {
	var out []string
	for _, h := range sources.HFHosts {
		out = append(out, h+"/"+repo+"/resolve/"+rev+"/"+file)
	}
	return out
}

// hfResolve pins a repository's current revision and lists its files.
func hfResolve(ctx context.Context, c *http.Client, repo string) (string, []hfEntry, error) {
	var lastErr error
	for _, h := range sources.HFHosts {
		var info struct {
			Sha string `json:"sha"`
		}
		if err := getJSON(ctx, c, h+"/api/models/"+repo+"/revision/main", &info); err != nil || info.Sha == "" {
			lastErr = fmt.Errorf("%s: %v", h, err)
			continue
		}
		var entries []hfEntry
		if err := getJSON(ctx, c, h+"/api/models/"+repo+"/tree/"+info.Sha+"?recursive=true", &entries); err != nil {
			lastErr = err
			continue
		}
		return info.Sha, entries, nil
	}
	return "", nil, lastErr
}
