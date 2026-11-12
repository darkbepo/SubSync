//go:build windows

package main

// subsync-cli.exe: the command-line version.  It shares the installation with
// SubSync.exe (same folder), installs/repairs with text progress, then runs
// app\cli.py on the console and passes its exit code through.

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"time"
)

const appVersionString = "1.3.0"

// Exit codes (also documented in README-CLI.md and app/subsync/cli.py).
const (
	exitOK       = 0  // every pair was synced
	exitPartial  = 3  // some pairs synced, some failed or did not match their video
	exitNone     = 4  // no pair could be synced
	exitNothing  = 5  // no video + subtitle pairs found in the given paths
	exitUsage    = 6  // invalid command line (unknown option, missing file, ...)
	exitSetup    = 7  // downloading / repairing SubSync's own files failed or is not possible right now
	exitDamaged  = 8  // "check": the installation is incomplete or damaged
	exitStopped  = 9  // stopped with Ctrl+C
	exitInternal = 10 // unexpected error inside SubSync - see logs\cli.log
)

const cliHelp = `SubSync command line ` + appVersionString + `

Usage:
  subsync-cli sync <files or folders...> [options]   sync subtitles to their videos
  subsync-cli <files or folders...> [options]        (same as sync)
  subsync-cli serve [options]                        keep running for another program: pairs in on
                                                     stdin, results out on stdout (JSON lines, README-CLI.md)
  subsync-cli setup                                  download / repair SubSync's files
  subsync-cli check                                  report whether the installation is intact
  subsync-cli version
  subsync-cli help

Sync options:
  --pair VIDEO SUBTITLE   sync this exact pair (can be repeated); other paths are paired automatically
  --suffix en|eng         name results <video>.en.srt (default) or <video>.eng.srt
  --overwrite             replace an existing result; without it a new file <video>.en.#1.srt is written
  --keep-layout           keep the original line layout and capitals (timing is still fixed)
  --cpu                   don't use the NVIDIA GPU
  --report FILE.json      write a machine-readable report of every pair
  --output FILE.srt       with exactly one --pair: write the result to this file
                          (needs --overwrite if it exists; --suffix is then not used)
  --progress              print machine-readable progress lines (PROGRESS {json}), see README-CLI.md

Exit codes:
  0  every pair was synced
  3  some pairs synced, some failed or did not match their video
  4  no pair could be synced
  5  no video + subtitle pairs found
  6  invalid command line
  7  setup / repair failed or not possible right now
  8  (check) installation incomplete or damaged
  9  stopped with Ctrl+C
  10 unexpected error - see logs\cli.log

Details of every run are written to logs\cli.log in the SubSync folder.
`

func cliMain(args []string) int {
	if len(args) == 0 {
		fmt.Print(cliHelp)
		return exitUsage
	}
	switch strings.ToLower(args[0]) {
	case "help", "-h", "--help", "/?":
		fmt.Print(cliHelp)
		return exitOK
	case "version", "--version":
		fmt.Println("SubSync " + appVersionString)
		return exitOK
	case "setup":
		return cliSetup(false)
	case "check":
		return cliSetup(true)
	case "sync":
		return cliSync(args[1:])
	case "serve":
		return cliRun("serve", args[1:])
	}
	if _, err := os.Stat(args[0]); err == nil || strings.HasPrefix(args[0], "--") {
		return cliSync(args) // "subsync-cli D:\Shows\Season 1"
	}
	fmt.Fprintf(os.Stderr, "Unknown command or path: %s\nRun \"subsync-cli help\" for usage.\n", args[0])
	return exitUsage
}

// prepare makes sure SubSync's files are complete (repairing if possible).
func prepare(checkOnly bool) int {
	alone := namedMutex("Any")
	if alone && !checkOnly {
		killStrays(root)
	}
	loadState()
	loadSources()
	m := loadManifest()
	gpu := hasNvidiaDriver()
	needs := needsInstall(m, gpu)
	if checkOnly {
		if !needs {
			fmt.Println("Installation is complete and intact.")
			return exitOK
		}
		if len(lastProblems) > 0 {
			fmt.Println("Damaged or missing: " + strings.Join(lastProblems, ", "))
		} else {
			fmt.Println("SubSync is not fully installed yet.")
		}
		fmt.Println("Run \"subsync-cli setup\" to fix it.")
		return exitDamaged
	}
	if needs {
		if !alone {
			fmt.Fprintln(os.Stderr, "Some SubSync files need to be downloaded or repaired, but another SubSync (window or command line) is using this folder. Close it and try again.")
			return exitSetup
		}
		switch {
		case len(lastProblems) > 0:
			fmt.Println("Repairing: " + strings.Join(lastProblems, ", "))
			logLine("self-check (cli): re-downloading " + strings.Join(lastProblems, ", "))
		case isDone(pyKey(m)):
			fmt.Println("Downloading missing SubSync files…")
		default:
			fmt.Println("Setting up SubSync (one-time download, about 3 GB)…")
		}
		if err := consoleInstall(m, gpu); err != nil {
			logLine("setup failed (cli): " + err.Error())
			fmt.Fprintln(os.Stderr, "\nSetup failed: "+shortErr(err))
			fmt.Fprintln(os.Stderr, "Check the internet connection and run the command again – finished downloads are kept.")
			return exitSetup
		}
		logLine("setup complete (cli)")
	}
	if err := syncAppFiles(); err != nil {
		fmt.Fprintln(os.Stderr, "Could not unpack program files: "+err.Error())
		return exitSetup
	}
	return exitOK
}

func cliSetup(checkOnly bool) int {
	code := prepare(checkOnly)
	if code == exitOK && !checkOnly {
		fmt.Println("SubSync is installed and ready.")
	}
	return code
}

func consoleInstall(m *manifest, gpu bool) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	defer signal.Stop(sig)
	go func() {
		if _, ok := <-sig; ok {
			cancel()
		}
	}()
	st := &progressState{}
	stop := make(chan struct{})
	go func() {
		last := ""
		tk := time.NewTicker(500 * time.Millisecond)
		defer tk.Stop()
		for {
			select {
			case <-stop:
				return
			case <-tk.C:
			}
			st.mu.Lock()
			line := fmt.Sprintf("%3d%%  %s  %s", int(st.fraction*100), st.step, st.detail)
			st.mu.Unlock()
			if len(line) > 110 {
				line = line[:109] + "…"
			}
			if line != last {
				fmt.Printf("\r%-110s", line)
				last = line
			}
		}
	}()
	err := install(ctx, m, gpu, st)
	close(stop)
	fmt.Println()
	return err
}

func cliSync(args []string) int { return cliRun("sync", args) }

// cliRun prepares the installation, then runs app\cli.py <command> <args...>.
func cliRun(command string, args []string) int {
	if code := prepare(false); code != exitOK {
		return code
	}
	py := filepath.Join(pyDir(), "python.exe")
	if !fileExists(py) {
		py = filepath.Join(pyDir(), "pythonw.exe")
	}
	cmd := exec.Command(py, append([]string{"-X", "utf8", filepath.Join(root, "app", "cli.py"), command}, args...)...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if wd, err := os.Getwd(); err == nil {
		cmd.Dir = wd // relative paths on the command line keep working
	}
	cmd.Env = appEnv()
	job := newKillOnCloseJob()
	defer killJob(job)
	// Ctrl+C reaches the Python side directly (same console); it stops cleanly
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	defer signal.Stop(sig)
	if err := cmd.Start(); err != nil {
		fmt.Fprintln(os.Stderr, "Could not start SubSync: "+err.Error())
		return exitInternal
	}
	assignToJob(job, cmd.Process.Pid)
	_ = cmd.Wait()
	code := 0
	if cmd.ProcessState != nil {
		code = cmd.ProcessState.ExitCode()
	}
	if uint32(code) >= 0xC0000000 {
		fmt.Fprintf(os.Stderr, "\nSubSync stopped unexpectedly (%s).\nDetails: %s\n", exitReason(uint32(code)),
			filepath.Join(root, "logs", "cli.log"))
		return exitInternal
	}
	return code
}
