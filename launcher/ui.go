//go:build windows

package main

import (
	"fmt"
	"math"
	"sync"
	"syscall"
	"unsafe"
)

// Custom-drawn, theme-aware setup window (follows Windows light/dark mode).
// Shapes are anti-aliased with GDI+, text is ClearType GDI, all double-buffered.

var (
	gdiplus  = syscall.NewLazyDLL("gdiplus.dll")
	dwmapi   = syscall.NewLazyDLL("dwmapi.dll")
	advapi32 = syscall.NewLazyDLL("advapi32.dll")

	pGdiplusStartup        = gdiplus.NewProc("GdiplusStartup")
	pGdipCreateFromHDC     = gdiplus.NewProc("GdipCreateFromHDC")
	pGdipDeleteGraphics    = gdiplus.NewProc("GdipDeleteGraphics")
	pGdipSetSmoothingMode  = gdiplus.NewProc("GdipSetSmoothingMode")
	pGdipCreateSolidFill   = gdiplus.NewProc("GdipCreateSolidFill")
	pGdipDeleteBrush       = gdiplus.NewProc("GdipDeleteBrush")
	pGdipCreatePath        = gdiplus.NewProc("GdipCreatePath")
	pGdipDeletePath        = gdiplus.NewProc("GdipDeletePath")
	pGdipAddPathArcI       = gdiplus.NewProc("GdipAddPathArcI")
	pGdipClosePathFigure   = gdiplus.NewProc("GdipClosePathFigure")
	pGdipFillPath          = gdiplus.NewProc("GdipFillPath")
	pGdipGraphicsClear     = gdiplus.NewProc("GdipGraphicsClear")
	pGdipFillRectangleI    = gdiplus.NewProc("GdipFillRectangleI")
	pDwmSetWindowAttribute = dwmapi.NewProc("DwmSetWindowAttribute")
	pRegGetValueW          = advapi32.NewProc("RegGetValueW")

	pBeginPaint             = user32.NewProc("BeginPaint")
	pEndPaint               = user32.NewProc("EndPaint")
	pGetClientRect          = user32.NewProc("GetClientRect")
	pInvalidateRect         = user32.NewProc("InvalidateRect")
	pDrawTextW              = user32.NewProc("DrawTextW")
	pSetCursor              = user32.NewProc("SetCursor")
	pTrackMouseEvent        = user32.NewProc("TrackMouseEvent")
	pDrawIconEx             = user32.NewProc("DrawIconEx")
	pLoadImageW             = user32.NewProc("LoadImageW")
	pCreateCompatibleDC     = gdi32.NewProc("CreateCompatibleDC")
	pCreateCompatibleBitmap = gdi32.NewProc("CreateCompatibleBitmap")
	pSelectObject           = gdi32.NewProc("SelectObject")
	pBitBlt                 = gdi32.NewProc("BitBlt")
	pDeleteObject           = gdi32.NewProc("DeleteObject")
	pDeleteDC               = gdi32.NewProc("DeleteDC")
	pSetBkMode              = gdi32.NewProc("SetBkMode")
)

const (
	wmPaint      = 0x000F
	wmEraseBkgnd = 0x0014
	wmSetCursor  = 0x0020
	wmKeyDown    = 0x0100
	wmMouseMove  = 0x0200
	wmLButtonUp  = 0x0202
	wmMouseLeave = 0x02A3
	vkEscape     = 0x1B
	vkReturn     = 0x0D
	dtLeft       = 0x0
	dtCenter     = 0x1
	dtRight      = 0x2
	dtVCenter    = 0x4
	dtSingleLine = 0x20
	dtNoPrefix   = 0x800
	dtPathEll    = 0x4000
	dtEndEll     = 0x8000
	idcHand      = 32649
)

type theme struct {
	bg, text, sub, track, accent, accentHover, btn, btnHover, btnBorder, danger uint32 // 0xRRGGBB
}

var lightTheme = theme{0xF7F8FA, 0x1B1D21, 0x646B76, 0xE2E5EA, 0x2B6CFF, 0x1F5BE6, 0xFFFFFF, 0xF0F2F5, 0xD6DAE1, 0xD64545}
var darkTheme = theme{0x1C1D21, 0xF2F3F5, 0xA0A6B1, 0x34363C, 0x4C84FF, 0x6696FF, 0x2B2D32, 0x35373D, 0x43464D, 0xFF6B6B}

// progressState is written by the installer goroutine and read by the UI timer.
type progressState struct {
	mu       sync.Mutex
	step     string
	detail   string
	fraction float64
	failed   bool
	finished bool
}

func (p *progressState) set(step, detail string, frac float64) {
	p.mu.Lock()
	if step != "" {
		p.step = step
	}
	p.detail = detail
	if frac >= 0 {
		p.fraction = frac
	}
	p.mu.Unlock()
}

type snapshot struct {
	step, detail     string
	fraction         float64
	failed, finished bool
}

type installWindow struct {
	hwnd           uintptr
	dpi            int
	th             theme
	root           string
	state          *progressState
	snap           snapshot
	shownFrac      float64
	hover, tracked bool
	onRetry        func()
	onCancel       func()
	closeOK        bool
	fTitle, fBody  uintptr
	fSmall         uintptr
	icon           uintptr
	btn            rectT
}

var theWindow *installWindow

func (w *installWindow) s(v int) int32 { return int32(v * w.dpi / 96) }

func colorref(rgb uint32) uintptr { // 0xRRGGBB -> COLORREF 0x00BBGGRR
	return uintptr((rgb&0xFF)<<16 | rgb&0xFF00 | rgb>>16&0xFF)
}

func argb(rgb uint32) uintptr { return uintptr(0xFF000000 | rgb) }

func systemDark() bool {
	var v, size uint32 = 1, 4
	r, _, _ := pRegGetValueW.Call(0x80000001,
		uintptr(unsafe.Pointer(u16(`Software\Microsoft\Windows\CurrentVersion\Themes\Personalize`))),
		uintptr(unsafe.Pointer(u16("AppsUseLightTheme"))), 0x10, 0, uintptr(unsafe.Pointer(&v)), uintptr(unsafe.Pointer(&size)))
	return r == 0 && v == 0
}

func runInstallWindow(root string, st *progressState, onStart func(), onRetry func(), onCancel func()) {
	pSetProcessDpiAwarenessContext.Call(^uintptr(3)) // PER_MONITOR_AWARE_V2 (-4)
	var token uintptr
	in := struct {
		version  uint32
		cb       uintptr
		noThread int32
		noCodecs int32
	}{version: 1}
	pGdiplusStartup.Call(uintptr(unsafe.Pointer(&token)), uintptr(unsafe.Pointer(&in)), 0)

	dpi := 96
	if r, _, _ := pGetDpiForSystem.Call(); r != 0 {
		dpi = int(r)
	}
	w := &installWindow{dpi: dpi, root: root, state: st, onRetry: onRetry, onCancel: onCancel}
	w.th = lightTheme
	if systemDark() {
		w.th = darkTheme
	}
	theWindow = w

	hInst, _, _ := pGetModuleHandleW.Call(0)
	icon, _, _ := pLoadIconW.Call(hInst, 1)
	w.icon, _, _ = pLoadImageW.Call(hInst, 1, 1 /*IMAGE_ICON*/, uintptr(w.s(44)), uintptr(w.s(44)), 0)
	cursor, _, _ := pLoadCursorW.Call(0, idcArrow)
	wc := wndClassEx{
		lpfnWndProc:   syscall.NewCallback(wndProc),
		hInstance:     hInst,
		hIcon:         icon,
		hIconSm:       icon,
		hCursor:       cursor,
		lpszClassName: u16("SubSyncSetup"),
	}
	wc.cbSize = uint32(unsafe.Sizeof(wc))
	pRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))

	font := func(pt float64, weight int, face string) uintptr {
		height := -int(math.Round(pt * float64(dpi) / 72))
		h, _, _ := pCreateFontW.Call(uintptr(height), 0, 0, 0, uintptr(weight), 0, 0, 0, defaultCharset, 0, 0,
			clearTypeQuality, 0, uintptr(unsafe.Pointer(u16(face))))
		return h
	}
	w.fTitle = font(15, fwSemiBold, "Segoe UI Variable Display")
	w.fBody = font(10.5, fwNormal, "Segoe UI Variable Text")
	w.fSmall = font(9, fwNormal, "Segoe UI Variable Text")

	cw, ch := int(w.s(560)), int(w.s(262))
	style := uintptr(wsOverlapped | wsCaption | wsSysMenu | wsMinimizeBox)
	rc := rectT{0, 0, int32(cw), int32(ch)}
	pAdjustWindowRect.Call(uintptr(unsafe.Pointer(&rc)), style, 0)
	ww, wh := int(rc.right-rc.left), int(rc.bottom-rc.top)
	sx, _, _ := pGetSystemMetrics.Call(0)
	sy, _, _ := pGetSystemMetrics.Call(1)
	x, y := (int(sx)-ww)/2, (int(sy)-wh)/2-int(w.s(40))
	w.btn = rectT{w.s(560 - 24 - 112), w.s(262 - 22 - 36), w.s(560 - 24), w.s(262 - 22)}
	hwnd, _, _ := pCreateWindowExW.Call(0, uintptr(unsafe.Pointer(u16("SubSyncSetup"))),
		uintptr(unsafe.Pointer(u16("SubSync setup"))), style,
		uintptr(x), uintptr(y), uintptr(ww), uintptr(wh), 0, 0, hInst, 0)
	w.hwnd = hwnd

	// title bar matches the theme; rounded corners on Windows 11
	dark := uint32(0)
	if w.th == darkTheme {
		dark = 1
	}
	pDwmSetWindowAttribute.Call(hwnd, 20, uintptr(unsafe.Pointer(&dark)), 4)
	corner := uint32(2)
	pDwmSetWindowAttribute.Call(hwnd, 33, uintptr(unsafe.Pointer(&corner)), 4)

	pShowWindow.Call(hwnd, swShow)
	pUpdateWindow.Call(hwnd)
	pSetForegroundWindow.Call(hwnd)
	pSetTimer.Call(hwnd, 1, 33, 0)
	onStart()

	var m msgT
	for {
		r, _, _ := pGetMessageW.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r) <= 0 {
			break
		}
		pTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
		pDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
	}
}

// ---------------------------------------------------------------- drawing
func fillRound(g uintptr, x, y, cx, cy, r int32, rgb uint32) {
	if cx <= 0 || cy <= 0 {
		return
	}
	if r*2 > cy {
		r = cy / 2
	}
	if r*2 > cx {
		r = cx / 2
	}
	var path, brush uintptr
	pGdipCreateSolidFill.Call(argb(rgb), uintptr(unsafe.Pointer(&brush)))
	d := r * 2
	if d <= 0 {
		pGdipFillRectangleI.Call(g, brush, uintptr(x), uintptr(y), uintptr(cx), uintptr(cy))
		pGdipDeleteBrush.Call(brush)
		return
	}
	pGdipCreatePath.Call(0, uintptr(unsafe.Pointer(&path)))
	arc := func(ax, ay int32, start, sweep float32) {
		// the angles are the 6th/7th arguments, i.e. passed on the stack, so raw float bits are correct
		pGdipAddPathArcI.Call(path, uintptr(ax), uintptr(ay), uintptr(d), uintptr(d),
			uintptr(math.Float32bits(start)), uintptr(math.Float32bits(sweep)))
	}
	arc(x, y, 180, 90)
	arc(x+cx-d, y, 270, 90)
	arc(x+cx-d, y+cy-d, 0, 90)
	arc(x, y+cy-d, 90, 90)
	pGdipClosePathFigure.Call(path)
	pGdipFillPath.Call(g, brush, path)
	pGdipDeleteBrush.Call(brush)
	pGdipDeletePath.Call(path)
}

func (w *installWindow) text(dc uintptr, s string, font uintptr, rgb uint32, l, t, r, b int32, flags uintptr) {
	pSelectObject.Call(dc, font)
	pSetTextColor.Call(dc, colorref(rgb))
	rc := rectT{l, t, r, b}
	pDrawTextW.Call(dc, uintptr(unsafe.Pointer(u16(s))), ^uintptr(0), uintptr(unsafe.Pointer(&rc)), flags|dtNoPrefix)
}

func (w *installWindow) paint() {
	var ps [80]byte
	hdc, _, _ := pBeginPaint.Call(w.hwnd, uintptr(unsafe.Pointer(&ps[0])))
	var cr rectT
	pGetClientRect.Call(w.hwnd, uintptr(unsafe.Pointer(&cr)))
	W, H := cr.right, cr.bottom
	mem, _, _ := pCreateCompatibleDC.Call(hdc)
	bmp, _, _ := pCreateCompatibleBitmap.Call(hdc, uintptr(W), uintptr(H))
	old, _, _ := pSelectObject.Call(mem, bmp)
	th, sn, b := w.th, &w.snap, w.btn

	// shapes, anti-aliased
	var g uintptr
	pGdipCreateFromHDC.Call(mem, uintptr(unsafe.Pointer(&g)))
	pGdipSetSmoothingMode.Call(g, 4)
	pGdipGraphicsClear.Call(g, argb(th.bg))
	barX, barY, barW, barH := w.s(24), w.s(150), W-w.s(48), w.s(8)
	fillRound(g, barX, barY, barW, barH, barH/2, th.track)
	if fill := int32(float64(barW) * w.shownFrac); fill > 0 {
		col := th.accent
		if sn.failed {
			col = th.danger
		}
		if fill < barH {
			fill = barH
		}
		fillRound(g, barX, barY, fill, barH, barH/2, col)
	}
	primary := sn.failed
	if primary {
		c := th.accent
		if w.hover {
			c = th.accentHover
		}
		fillRound(g, b.left, b.top, b.right-b.left, b.bottom-b.top, w.s(6), c)
	} else {
		one := w.s(1)
		if one < 1 {
			one = 1
		}
		c := th.btn
		if w.hover {
			c = th.btnHover
		}
		fillRound(g, b.left, b.top, b.right-b.left, b.bottom-b.top, w.s(6), th.btnBorder)
		fillRound(g, b.left+one, b.top+one, b.right-b.left-2*one, b.bottom-b.top-2*one, w.s(6)-one, c)
	}
	pGdipDeleteGraphics.Call(g)

	// icon + text
	pDrawIconEx.Call(mem, uintptr(w.s(24)), uintptr(w.s(22)), w.icon, uintptr(w.s(44)), uintptr(w.s(44)), 0, 0, 3)
	pSetBkMode.Call(mem, 1)
	left := w.s(24 + 44 + 14)
	w.text(mem, setupTitle, w.fTitle, th.text, left, w.s(20), W-w.s(24), w.s(46), dtLeft|dtSingleLine|dtVCenter)
	w.text(mem, setupSubtitle, w.fSmall, th.sub, left, w.s(46), W-w.s(24), w.s(66), dtLeft|dtSingleLine|dtVCenter)
	stepCol := th.text
	if sn.failed {
		stepCol = th.danger
	}
	w.text(mem, sn.step, w.fBody, stepCol, w.s(24), w.s(114), W-w.s(24), w.s(140), dtLeft|dtSingleLine|dtVCenter|dtEndEll)
	w.text(mem, sn.detail, w.fSmall, th.sub, w.s(24), w.s(166), W-w.s(80), w.s(186), dtLeft|dtSingleLine|dtVCenter|dtEndEll)
	w.text(mem, fmt.Sprintf("%d%%", int(sn.fraction*100+1e-4)), w.fSmall, th.sub, W-w.s(80), w.s(166), W-w.s(24), w.s(186), dtRight|dtSingleLine|dtVCenter)
	w.text(mem, w.root, w.fSmall, th.sub, w.s(24), b.top, b.left-w.s(16), b.bottom, dtLeft|dtSingleLine|dtVCenter|dtPathEll)
	label, lc := "Cancel", th.text
	if primary {
		label, lc = "Retry", 0xFFFFFF
	}
	w.text(mem, label, w.fBody, lc, b.left, b.top, b.right, b.bottom, dtCenter|dtSingleLine|dtVCenter)

	pBitBlt.Call(hdc, 0, 0, uintptr(W), uintptr(H), mem, 0, 0, 0x00CC0020)
	pSelectObject.Call(mem, old)
	pDeleteObject.Call(bmp)
	pDeleteDC.Call(mem)
	pEndPaint.Call(w.hwnd, uintptr(unsafe.Pointer(&ps[0])))
}

func (w *installWindow) tick() {
	s := w.state
	s.mu.Lock()
	sn := snapshot{s.step, s.detail, s.fraction, s.failed, s.finished}
	s.mu.Unlock()
	if sn.finished {
		w.closeOK = true
		pDestroyWindow.Call(w.hwnd)
		return
	}
	// glide the bar towards the real value instead of jumping
	diff := sn.fraction - w.shownFrac
	moving := math.Abs(diff) >= 0.0005
	if moving {
		w.shownFrac += diff * 0.18
	} else {
		w.shownFrac = sn.fraction
	}
	if moving || sn.step != w.snap.step || sn.detail != w.snap.detail || sn.failed != w.snap.failed ||
		int(sn.fraction*100) != int(w.snap.fraction*100) {
		w.snap = sn
		pInvalidateRect.Call(w.hwnd, 0, 0)
	}
	w.snap = sn
}

func (w *installWindow) inButton(lParam uintptr) bool {
	x, y := int32(int16(lParam&0xffff)), int32(int16(lParam>>16&0xffff))
	return x >= w.btn.left && x < w.btn.right && y >= w.btn.top && y < w.btn.bottom
}

func (w *installWindow) press() {
	if w.snap.failed {
		w.state.mu.Lock()
		w.state.failed = false
		w.state.mu.Unlock()
		w.onRetry()
	} else if w.askClose() {
		w.onCancel()
		w.closeOK = true
		pDestroyWindow.Call(w.hwnd)
	}
}

func (w *installWindow) askClose() bool {
	if w.snap.failed {
		return true
	}
	return messageBox(w.hwnd, "Setup is not finished yet.\n\nClose anyway? Next time SubSync starts it continues where it left off.",
		"SubSync", mbYesNo|mbIconWarning) == idYes
}

func wndProc(hwnd, msg, wParam, lParam uintptr) uintptr {
	w := theWindow
	if w == nil || w.hwnd == 0 {
		r, _, _ := pDefWindowProcW.Call(hwnd, msg, wParam, lParam)
		return r
	}
	switch msg {
	case wmPaint:
		w.paint()
		return 0
	case wmEraseBkgnd:
		return 1
	case wmTimer:
		w.tick()
		return 0
	case wmMouseMove:
		if !w.tracked {
			tme := struct {
				size, flags uint32
				hwnd        uintptr
				hover       uint32
				_           uint32
			}{24, 2 /*TME_LEAVE*/, hwnd, 0, 0}
			pTrackMouseEvent.Call(uintptr(unsafe.Pointer(&tme)))
			w.tracked = true
		}
		if h := w.inButton(lParam); h != w.hover {
			w.hover = h
			pInvalidateRect.Call(hwnd, 0, 0)
		}
		return 0
	case wmMouseLeave:
		w.tracked = false
		if w.hover {
			w.hover = false
			pInvalidateRect.Call(hwnd, 0, 0)
		}
		return 0
	case wmSetCursor:
		if w.hover {
			c, _, _ := pLoadCursorW.Call(0, idcHand)
			pSetCursor.Call(c)
			return 1
		}
	case wmLButtonUp:
		if w.inButton(lParam) {
			w.press()
		}
		return 0
	case wmKeyDown:
		if wParam == vkEscape || (wParam == vkReturn && w.snap.failed) {
			w.press()
		}
		return 0
	case wmClose:
		if !w.closeOK && !w.askClose() {
			return 0
		}
		if !w.closeOK {
			w.onCancel()
		}
		pDestroyWindow.Call(hwnd)
		return 0
	case wmDestroy:
		pPostQuitMessage.Call(0)
		return 0
	}
	r, _, _ := pDefWindowProcW.Call(hwnd, msg, wParam, lParam)
	return r
}

func humanBytes(n int64) string {
	f := float64(n)
	switch {
	case f >= 1<<30:
		return fmt.Sprintf("%.2f GB", f/(1<<30))
	case f >= 1<<20:
		return fmt.Sprintf("%.0f MB", f/(1<<20))
	default:
		return fmt.Sprintf("%.0f KB", f/(1<<10))
	}
}
