package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func TestMaintenanceBackupRestoreRotationAndTamper(t *testing.T) {
	s, _ := fixture(t)
	s.store.Messages[testMessage().ID] = testMessage()
	if err := s.store.save(); err != nil {
		t.Fatal(err)
	}
	base := t.TempDir()
	backup := filepath.Join(base, "backup")
	if err := maintainStore("backup", s.store.path, backup); err != nil {
		t.Fatal(err)
	}
	restored := filepath.Join(base, "restored")
	if err := maintainStore("restore", backup, restored); err != nil {
		t.Fatal(err)
	}
	copy, err := openStore(filepath.Join(restored, "privrelay.enc"))
	if err != nil || copy.Messages[testMessage().ID].Body != testMessage().Body {
		t.Fatal("restore lost content", err)
	}
	if err = maintainStore("backup", s.store.path, backup); err == nil {
		t.Fatal("overwrote backup")
	}
	rotated := filepath.Join(base, "rotated")
	if err = maintainStore("rotate-key", s.store.path, rotated); err != nil {
		t.Fatal(err)
	}
	rekeyed, err := openStore(filepath.Join(rotated, "privrelay.enc"))
	if err != nil || rekeyed.Messages[testMessage().ID].Body != testMessage().Body || bytes.Equal(rekeyed.key, s.store.key) {
		t.Fatal("rotation failed", err)
	}
	original, err := openStore(s.store.path)
	if err != nil || !bytes.Equal(original.key, s.store.key) {
		t.Fatal("rotation modified source", err)
	}
	if err = os.WriteFile(filepath.Join(backup, "privrelay.enc"), []byte("tampered"), 0600); err != nil {
		t.Fatal(err)
	}
	rejected := filepath.Join(base, "rejected")
	if err = maintainStore("restore", backup, rejected); err == nil {
		t.Fatal("accepted corrupt backup")
	}
	if _, err = os.Stat(rejected); !os.IsNotExist(err) {
		t.Fatal("created output for corrupt backup")
	}
}
func TestStoreLockRejectsSecondProcessAndMaintenance(t *testing.T) {
	s, _ := fixture(t)
	if err := s.store.save(); err != nil {
		t.Fatal(err)
	}
	lock, err := lockStore(s.store.path)
	if err != nil {
		t.Fatal(err)
	}
	if second, err := lockStore(s.store.path); err == nil {
		second.Close()
		t.Fatal("second owner allowed")
	}
	if err = maintainStore("backup", s.store.path, filepath.Join(t.TempDir(), "backup")); err == nil {
		t.Fatal("backed up running store")
	}
	lock.Close()
	next, err := lockStore(s.store.path)
	if err != nil {
		t.Fatal("lock not released", err)
	}
	next.Close()
}
