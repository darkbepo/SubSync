//go:build windows

package main

// Process supervision: SubSync.exe stays alive (hidden, a few MB) for as long as
// the app runs.  The app and every helper process it starts are placed in a
// Windows Job Object with KILL_ON_JOB_CLOSE, so when the app closes, crashes or
// fails to start - or SubSync.exe itself is killed - Windows terminates every
// process in the job.  Nothing can be left running.

import (
	"crypto/sha1"
	"encoding/hex"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

var (
	pCreateJobObjectW          = kernel32.NewProc("CreateJobObjectW")
	pSetInformationJobObject   = kernel32.NewProc("SetInformationJobObject")
	pAssignProcessToJobObject  = kernel32.NewProc("AssignProcessToJobObject")
	pTerminateJobObject        = kernel32.NewProc("TerminateJobObject")
	pOpenProcess               = kernel32.NewProc("OpenProcess")
	pTerminateProcess          = kernel32.NewProc("TerminateProcess")
	pWaitForSingleObject       = kernel32.NewProc("WaitForSingleObject")
	pCreateToolhelp32Snapshot  = kernel32.NewProc("CreateToolhelp32Snapshot")
	pProcess32FirstW           = kernel32.NewProc("Process32FirstW")
	pProcess32NextW            = kernel32.NewProc("Process32NextW")
	pQueryFullProcessImageName = kernel32.NewProc("QueryFullProcessImageNameW")
	pCreateMutexW              = kernel32.NewProc("CreateMutexW")
	pFindWindowW               = user32.NewProc("FindWindowW")
	pIsIconic                  = user32.NewProc("IsIconic")
	pAllowSetForegroundWindow  = user32.NewProc("AllowSetForegroundWindow")
)

const (
	processTerminate        = 0x0001
	processSetQuota         = 0x0100
	processQueryLimitedInfo = 0x1000
	synchronize             = 0x00100000
	jobKillOnClose          = 0x2000
	jobExtendedLimitInfo    = 9
	th32csSnapProcess       = 0x2
	errorAlreadyExists      = 183
)

type jobBasicLimit struct {
	PerProcessUserTimeLimit int64
	PerJobUserTimeLimit     int64
	LimitFlags              uint32
	MinimumWorkingSetSize   uintptr
	MaximumWorkingSetSize   uintptr
	ActiveProcessLimit      uint32
	Affinity                uintptr
	PriorityClass           uint32
	SchedulingClass         uint32
}

type jobExtendedLimit struct {
	Basic                 jobBasicLimit
	IoInfo                [6]uint64
	ProcessMemoryLimit    uintptr
	JobMemoryLimit        uintptr
	PeakProcessMemoryUsed uintptr
	PeakJobMemoryUsed     uintptr
}

type processEntry32 struct {
	Size            uint32
	Usage           uint32
	ProcessID       uint32
	DefaultHeapID   uintptr
	ModuleID        uint32
	Threads         uint32
	ParentProcessID uint32
	PriClassBase    int32
	Flags           uint32
	ExeFile         [260]uint16
}

// newKillOnCloseJob returns a job handle; closing it (or this process dying) kills every member.
func newKillOnCloseJob() uintptr {
	job, _, _ := pCreateJobObjectW.Call(0, 0)
	if job == 0 {
		return 0
	}
	var info jobExtendedLimit
	info.Basic.LimitFlags = jobKillOnClose
	pSetInformationJobObject.Call(job, jobExtendedLimitInfo, uintptr(unsafe.Pointer(&info)), unsafe.Sizeof(info))
	return job
}

func assignToJob(job uintptr, pid int) {
	if job == 0 {
		return
	}
	h, _, _ := pOpenProcess.Call(processSetQuota|processTerminate, 0, uintptr(pid))
	if h == 0 {
		return
	}
	pAssignProcessToJobObject.Call(job, h)
	syscall.CloseHandle(syscall.Handle(h))
}

func killJob(job uintptr) {
	if job != 0 {
		pTerminateJobObject.Call(job, 1)
	}
}

// namedMutex creates a per-folder named mutex and returns false if another
// SubSync process already holds one with that name.  The handle stays open for
// the life of this process.
func namedMutex(kind string) bool {
	sum := sha1.Sum([]byte(strings.ToLower(root)))
	name := "Local\\SubSync-" + kind + "-" + hex.EncodeToString(sum[:8])
	h, _, err := pCreateMutexW.Call(0, 0, uintptr(unsafe.Pointer(u16(name))))
	if h == 0 {
		return true
	}
	if errno, ok := err.(syscall.Errno); ok && errno == errorAlreadyExists {
		return false
	}
	return true
}

// focusExisting brings an already-open SubSync window to the front.
func focusExisting() {
	for _, title := range []string{"SubSync", "SubSync setup"} {
		h, _, _ := pFindWindowW.Call(0, uintptr(unsafe.Pointer(u16(title))))
		if h != 0 {
			if r, _, _ := pIsIconic.Call(h); r != 0 {
				pShowWindow.Call(h, 9) // SW_RESTORE
			}
			pSetForegroundWindow.Call(h)
			return
		}
	}
}

// killStrays ends any process whose program lives inside this tool's folder
// (leftovers from an older version or a crash).  Only called when no other
// SubSync instance from this folder is running.
func killStrays(root string) int {
	runtimeDir := strings.ToLower(filepath.Join(root, "runtime")) + `\`
	snap, _, _ := pCreateToolhelp32Snapshot.Call(th32csSnapProcess, 0)
	if snap == 0 || snap == ^uintptr(0) {
		return 0
	}
	defer syscall.CloseHandle(syscall.Handle(snap))
	var e processEntry32
	e.Size = uint32(unsafe.Sizeof(e))
	killed := 0
	for r, _, _ := pProcess32FirstW.Call(snap, uintptr(unsafe.Pointer(&e))); r != 0; r, _, _ = pProcess32NextW.Call(snap, uintptr(unsafe.Pointer(&e))) {
		h, _, _ := pOpenProcess.Call(processQueryLimitedInfo|processTerminate|synchronize, 0, uintptr(e.ProcessID))
		if h == 0 {
			continue
		}
		buf := make([]uint16, 1024)
		n := uint32(len(buf))
		if ok, _, _ := pQueryFullProcessImageName.Call(h, 0, uintptr(unsafe.Pointer(&buf[0])), uintptr(unsafe.Pointer(&n))); ok != 0 {
			p := strings.ToLower(syscall.UTF16ToString(buf[:n]))
			if strings.HasPrefix(p, runtimeDir) {
				pTerminateProcess.Call(h, 1)
				pWaitForSingleObject.Call(h, 3000)
				killed++
			}
		}
		syscall.CloseHandle(syscall.Handle(h))
	}
	return killed
}
