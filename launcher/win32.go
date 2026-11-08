//go:build windows

package main

import (
	"syscall"
	"unsafe"
)

var (
	user32   = syscall.NewLazyDLL("user32.dll")
	gdi32    = syscall.NewLazyDLL("gdi32.dll")
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	comctl32 = syscall.NewLazyDLL("comctl32.dll")

	pRegisterClassExW              = user32.NewProc("RegisterClassExW")
	pCreateWindowExW               = user32.NewProc("CreateWindowExW")
	pDefWindowProcW                = user32.NewProc("DefWindowProcW")
	pGetMessageW                   = user32.NewProc("GetMessageW")
	pTranslateMessage              = user32.NewProc("TranslateMessage")
	pDispatchMessageW              = user32.NewProc("DispatchMessageW")
	pIsDialogMessageW              = user32.NewProc("IsDialogMessageW")
	pPostQuitMessage               = user32.NewProc("PostQuitMessage")
	pSendMessageW                  = user32.NewProc("SendMessageW")
	pSetWindowTextW                = user32.NewProc("SetWindowTextW")
	pShowWindow                    = user32.NewProc("ShowWindow")
	pUpdateWindow                  = user32.NewProc("UpdateWindow")
	pSetTimer                      = user32.NewProc("SetTimer")
	pDestroyWindow                 = user32.NewProc("DestroyWindow")
	pMessageBoxW                   = user32.NewProc("MessageBoxW")
	pLoadIconW                     = user32.NewProc("LoadIconW")
	pLoadCursorW                   = user32.NewProc("LoadCursorW")
	pGetSystemMetrics              = user32.NewProc("GetSystemMetrics")
	pGetDpiForSystem               = user32.NewProc("GetDpiForSystem")
	pSetProcessDpiAwarenessContext = user32.NewProc("SetProcessDpiAwarenessContext")
	pGetSysColorBrush              = user32.NewProc("GetSysColorBrush")
	pGetSysColor                   = user32.NewProc("GetSysColor")
	pAdjustWindowRect              = user32.NewProc("AdjustWindowRect")
	pSetForegroundWindow           = user32.NewProc("SetForegroundWindow")

	pCreateFontW  = gdi32.NewProc("CreateFontW")
	pSetBkColor   = gdi32.NewProc("SetBkColor")
	pSetTextColor = gdi32.NewProc("SetTextColor")

	pGetModuleHandleW    = kernel32.NewProc("GetModuleHandleW")
	pGetDiskFreeSpaceExW = kernel32.NewProc("GetDiskFreeSpaceExW")

	pInitCommonControlsEx = comctl32.NewProc("InitCommonControlsEx")
)

const (
	wmDestroy        = 0x0002
	wmClose          = 0x0010
	wmSetFont        = 0x0030
	wmCommand        = 0x0111
	wmTimer          = 0x0113
	wmCtlColorStatic = 0x0138
	wsOverlapped     = 0x00000000
	wsCaption        = 0x00C00000
	wsSysMenu        = 0x00080000
	wsMinimizeBox    = 0x00020000
	wsChild          = 0x40000000
	wsVisible        = 0x10000000
	wsTabStop        = 0x00010000
	ssEndEllipsis    = 0x00004000
	ssPathEllipsis   = 0x00008000
	pbmSetRange32    = 0x0406
	pbmSetPos        = 0x0402
	pbsSmooth        = 0x01
	colorWindow      = 5
	colorWindowText  = 8
	colorGrayText    = 17
	mbOK             = 0x0
	mbYesNo          = 0x4
	mbIconError      = 0x10
	mbIconWarning    = 0x30
	mbIconInfo       = 0x40
	idYes            = 6
	swShow           = 5
	iccProgressClass = 0x20
	iccStandardClass = 0x4000
	cwUseDefault     = 0x80000000
	clearTypeQuality = 5
	fwNormal         = 400
	fwSemiBold       = 600
	idcArrow         = 32512
	defaultCharset   = 1
)

type wndClassEx struct {
	cbSize        uint32
	style         uint32
	lpfnWndProc   uintptr
	cbClsExtra    int32
	cbWndExtra    int32
	hInstance     uintptr
	hIcon         uintptr
	hCursor       uintptr
	hbrBackground uintptr
	lpszMenuName  *uint16
	lpszClassName *uint16
	hIconSm       uintptr
}

type point struct{ x, y int32 }

type msgT struct {
	hwnd     uintptr
	message  uint32
	wParam   uintptr
	lParam   uintptr
	time     uint32
	pt       point
	lPrivate uint32
}

type rectT struct{ left, top, right, bottom int32 }

func u16(s string) *uint16 {
	p, _ := syscall.UTF16PtrFromString(s)
	return p
}

func messageBox(hwnd uintptr, text, title string, flags uintptr) int {
	r, _, _ := pMessageBoxW.Call(hwnd, uintptr(unsafe.Pointer(u16(text))), uintptr(unsafe.Pointer(u16(title))), flags)
	return int(r)
}

func setText(hwnd uintptr, s string) {
	pSetWindowTextW.Call(hwnd, uintptr(unsafe.Pointer(u16(s))))
}

func freeDiskBytes(path string) uint64 {
	var free uint64
	r, _, _ := pGetDiskFreeSpaceExW.Call(uintptr(unsafe.Pointer(u16(path))), uintptr(unsafe.Pointer(&free)), 0, 0)
	if r == 0 {
		return 0
	}
	return free
}

func hasNvidiaDriver() bool {
	h, err := syscall.LoadLibrary("nvcuda.dll")
	if err != nil {
		return false
	}
	syscall.FreeLibrary(h)
	return true
}
