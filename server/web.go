package main

import (
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

func sameOrigin(r *http.Request) bool {
	u, err := url.Parse(r.Header.Get("Origin"))
	return err == nil && (u.Scheme == "http" || u.Scheme == "https") && u.Host == r.Host && u.User == nil && u.Path == "" && u.RawQuery == "" && u.Fragment == ""
}

func sessionCookie(r *http.Request, token string, maxAge int) *http.Cookie {
	return &http.Cookie{Name: "privrelay_session", Value: token, Path: "/api/v1", HttpOnly: true, Secure: r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https", SameSite: http.SameSiteStrictMode, MaxAge: maxAge}
}

func (s *Server) serveWeb(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" && r.Method != "HEAD" || strings.HasPrefix(r.URL.Path, "/api/") || s.webDir == "" {
		http.NotFound(w, r)
		return
	}
	// FileServer performs path cleaning and never exposes the data directory.
	if r.URL.Path == "/" {
		if _, err := os.Stat(filepath.Join(s.webDir, "index.html")); err != nil {
			writeJSON(w, 503, map[string]string{"error": "web_not_built"})
			return
		}
		w.Header().Set("Cache-Control", "no-store")
	}
	http.FileServer(http.Dir(s.webDir)).ServeHTTP(w, r)
}
