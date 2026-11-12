// Stand-in for runtime\python\python(w).exe in launcher tests. It never runs
// Python; it imitates the app's observable behaviour, chosen by <root>\mode.txt:
//
//	normal   start a helper process, signal "window ready", exit after 4 s
//	stay     like normal, but keep running (to test killing the launcher)
//	crash    start a helper, then die with an access violation before "ready"
//	exitN    print the arguments + working directory, exit with code N (CLI passthrough)
//
// "-m compileall ..." (setup's precompile step) writes <root>\precompiled.txt and exits at once.
// "--helper" = the child process (like the speech worker) that must never be left behind.
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == "--helper" {
		time.Sleep(300 * time.Second)
		return
	}
	root := os.Getenv("SUBSYNC_ROOT")
	for _, a := range os.Args[1:] {
		if a == "compileall" { // setup's precompile step: leave a marker and finish like Python would
			_ = os.WriteFile(filepath.Join(root, "precompiled.txt"), []byte(strings.Join(os.Args[1:], " ")), 0o644)
			return
		}
	}
	b, _ := os.ReadFile(filepath.Join(root, "mode.txt"))
	mode := strings.TrimSpace(string(b))
	if strings.HasPrefix(mode, "exit") {
		n, _ := strconv.Atoi(strings.TrimPrefix(mode, "exit"))
		wd, _ := os.Getwd()
		args := os.Args[1:]
		if len(args) > 2 {
			args = args[2:] // drop "-X utf8"
		}
		fmt.Println("python side got:", strings.Join(args, " "), "| cwd:", wd)
		os.Exit(n)
	}
	_ = exec.Command(os.Args[0], "--helper").Start()
	if mode == "crash" {
		time.Sleep(2 * time.Second)
		os.Exit(-1073741819) // 0xC0000005
	}
	_ = os.WriteFile(os.Getenv("SUBSYNC_READY_FILE"), []byte("ok"), 0o644)
	if mode == "stay" {
		time.Sleep(300 * time.Second)
	}
	time.Sleep(4 * time.Second)
}
