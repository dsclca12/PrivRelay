package main

import (
	"os"
	"syscall"
	"unsafe"
)

func lockStore(path string) (*os.File, error) {
	f, err := os.OpenFile(path+".lock", os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	var overlapped syscall.Overlapped
	proc := syscall.NewLazyDLL("kernel32.dll").NewProc("LockFileEx")
	result, _, callErr := proc.Call(f.Fd(), 3, 0, 1, 0, uintptr(unsafe.Pointer(&overlapped)))
	if result == 0 {
		f.Close()
		return nil, callErr
	}
	return f, nil
}

// Windows does not support directory fsync via os.File.Sync.
func syncDirectory(path string) error { return nil }
