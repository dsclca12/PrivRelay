package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"time"
)

type backupManifest struct {
	Version   int               `json:"version"`
	CreatedAt string            `json:"created_at"`
	Files     map[string]string `json:"sha256"`
}

// All operations hold the source lock. Every destination is a NEW private directory;
// no live files or previous backup can be overwritten, including during key rotation.
func maintainStore(action, source, destination string) error {
	if destination == "" {
		return errors.New("output directory required")
	}
	sourceFile := source
	if action == "restore" {
		sourceFile = filepath.Join(source, "privrelay.enc")
	}
	if _, err := os.Stat(sourceFile); err != nil {
		return err
	}
	lock, err := lockStore(sourceFile)
	if err != nil {
		return errors.New("store in use or cannot be locked")
	}
	defer lock.Close()
	if action == "restore" {
		if err = verifyBackup(source); err != nil {
			return err
		}
	}
	store, err := openStore(sourceFile)
	if err != nil {
		return err
	}
	if action != "backup" && action != "restore" && action != "rotate-key" {
		return errors.New("unknown maintenance action")
	}
	if err = os.Mkdir(destination, 0700); err != nil {
		return err
	}
	success := false
	defer func() {
		if !success {
			os.RemoveAll(destination)
		}
	}()
	target := filepath.Join(destination, "privrelay.enc")
	if action == "rotate-key" {
		rotatedKey := make([]byte, 32)
		if _, err = rand.Read(rotatedKey); err != nil {
			return err
		}
		if err = writePrivate(target+".key", rotatedKey); err != nil {
			return err
		}
		store.path, store.key = target, rotatedKey
		if err = store.save(); err != nil {
			return err
		}
	} else {
		for _, suffix := range []string{".key", ""} {
			var raw []byte
			if suffix == ".key" && os.Getenv("PRIVRELAY_STORAGE_KEY") != "" {
				raw = store.key
			} else {
				var e error
				raw, e = os.ReadFile(sourceFile + suffix)
				if e != nil {
					return e
				}
			}
			if err = writePrivate(target+suffix, raw); err != nil {
				return err
			}
		}
	}
	manifest := backupManifest{Version: 1, CreatedAt: time.Now().UTC().Format(time.RFC3339), Files: map[string]string{}}
	for _, name := range []string{"privrelay.enc", "privrelay.enc.key"} {
		raw, e := os.ReadFile(filepath.Join(destination, name))
		if e != nil {
			return e
		}
		sum := sha256.Sum256(raw)
		manifest.Files[name] = hex.EncodeToString(sum[:])
	}
	raw, _ := json.MarshalIndent(manifest, "", "  ")
	if err = writePrivate(filepath.Join(destination, "manifest.json"), raw); err != nil {
		return err
	}
	if err = syncDirectory(destination); err != nil {
		return err
	}
	if err = syncDirectory(filepath.Dir(destination)); err != nil {
		return err
	}
	success = true
	return nil
}
func writePrivate(path string, raw []byte) error {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	return closeErr
}
func verifyBackup(directory string) error {
	raw, err := os.ReadFile(filepath.Join(directory, "manifest.json"))
	if err != nil {
		return err
	}
	var m backupManifest
	if json.Unmarshal(raw, &m) != nil || m.Version != 1 || len(m.Files) != 2 {
		return errors.New("invalid backup manifest")
	}
	for _, name := range []string{"privrelay.enc", "privrelay.enc.key"} {
		raw, err = os.ReadFile(filepath.Join(directory, name))
		if err != nil {
			return err
		}
		sum := sha256.Sum256(raw)
		if hex.EncodeToString(sum[:]) != m.Files[name] {
			return errors.New("backup checksum mismatch")
		}
	}
	return nil
}
