package main

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"github.com/gorilla/websocket"
	"io"
	"log"
	"math"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

type Server struct {
	mu                        sync.Mutex
	store                     *Store
	code                      string
	codeExpires               time.Time
	classifier, classifierKey string
	client                    *http.Client
	peers                     map[*websocket.Conn]string
	peerSignals               map[*websocket.Conn]chan struct{}
	retryCursor               string
	failures                  map[string]int
	webDir                    string
}

func randomToken() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}
func hash(raw string) string { h := sha256.Sum256([]byte(raw)); return hex.EncodeToString(h[:]) }
func newServer(store *Store, classifier string) *Server {
	return &Server{store: store, code: randomToken(), codeExpires: time.Now().Add(10 * time.Minute), classifier: classifier,
		client: &http.Client{Timeout: 3 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("redirect disabled") }}, peers: map[*websocket.Conn]string{}, peerSignals: map[*websocket.Conn]chan struct{}{}, failures: map[string]int{}}
}
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func readJSON(w http.ResponseWriter, r *http.Request, v any) bool {
	return readJSONLimit(w, r, v, 512*1024)
}
func readJSONLimit(w http.ResponseWriter, r *http.Request, v any, limit int64) bool {
	r.Body = http.MaxBytesReader(w, r.Body, limit)
	decoder := json.NewDecoder(r.Body)
	reject := func(err error) bool {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			writeJSON(w, 413, map[string]string{"error": "request_too_large"})
			return false
		}
		writeJSON(w, 400, map[string]string{"error": "invalid_request"})
		return false
	}
	if err := decoder.Decode(v); err != nil {
		return reject(err)
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		return reject(err)
	}
	return true
}
func (s *Server) auth(r *http.Request) (Device, bool) {
	raw := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if raw == "" || raw == r.Header.Get("Authorization") {
		cookie, err := r.Cookie("privrelay_session")
		if err != nil || (r.Method != "GET" && !sameOrigin(r)) {
			return Device{}, false
		}
		raw = cookie.Value
	}
	digest := hash(raw)
	for _, d := range s.store.Devices {
		if d.Active && d.Expires > time.Now().Unix() && subtle.ConstantTimeCompare([]byte(d.TokenHash), []byte(digest)) == 1 {
			return d, true
		}
	}
	return Device{}, false
}

// Every acknowledged mutation is durable. Roll back memory when disk commit fails.
func (s *Server) commit(w http.ResponseWriter, before []byte) bool {
	if err := s.store.save(); err != nil {
		s.rollback(before)
		writeJSON(w, 503, map[string]string{"error": "storage_unavailable"})
		return false
	}
	return true
}
func (s *Server) snapshot() []byte { b, _ := json.Marshal(s.store); return b }
func (s *Server) rollback(raw []byte) {
	var previous Store
	if err := json.Unmarshal(raw, &previous); err != nil {
		panic("invalid internal snapshot")
	}
	previous.path = s.store.path
	previous.key = s.store.key
	*s.store = previous
}
func (s *Server) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.serveWeb)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		status := "unavailable"
		if s.classifier != "" {
			response, err := s.client.Get(strings.TrimRight(s.classifier, "/") + "/healthz")
			if err == nil {
				if response.StatusCode == 200 {
					status = "ok"
				}
				response.Body.Close()
			}
		}
		writeJSON(w, 200, map[string]string{"status": "ok", "classifier": status})
	})
	mux.HandleFunc("POST /api/v1/devices/register", s.register)
	apiHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		defer s.mu.Unlock()
		d, ok := s.auth(r)
		if !ok {
			writeJSON(w, 401, map[string]string{"error": "pairing_required"})
			return
		}
		path := r.URL.Path
		if (d.E2EE || s.store.E2EEEnabled) && (path == "/api/v1/messages/sync" || path == "/api/v1/messages" ||
			path == "/api/v1/messages/search" || path == "/api/v1/filter/quarantine" ||
			strings.HasPrefix(path, "/api/v1/messages/") || strings.HasPrefix(path, "/api/v1/feedback")) {
			writeJSON(w, 403, map[string]string{"error": "e2ee_only"})
			return
		}
		if path == "/api/v2/encrypted-messages/sync" && r.Method == "POST" {
			s.syncEncryptedMessages(w, r, d)
			return
		}
		if path == "/api/v2/crypto/params" && r.Method == "GET" {
			writeJSON(w, 200, map[string]any{"version": 1, "kdf": "PBKDF2-SHA256", "iterations": 600000, "salt": s.store.VaultSalt})
			return
		}
		if path == "/api/v2/encrypted-messages" && r.Method == "GET" {
			if !d.E2EE {
				writeJSON(w, 403, map[string]string{"error": "e2ee_required"})
				return
			}
			s.listEncryptedMessages(w, r)
			return
		}
		if path == "/api/v2/legacy-migration" && r.Method == "POST" {
			s.migrateLegacyMessages(w, r, d)
			return
		}
		if path == "/api/v1/ws" && r.Method == "GET" {
			s.websocket(w, r, d)
			return
		}
		switch {
		case path == "/api/v1/session" && r.Method == "POST":
			// Only a bearer-authenticated client may establish a browser session.
			if !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") || !sameOrigin(r) {
				writeJSON(w, 403, map[string]string{"error": "origin_rejected"})
				return
			}
			http.SetCookie(w, sessionCookie(r, strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "), int(time.Until(time.Unix(d.Expires, 0)).Seconds())))
			writeJSON(w, 200, d.ID)
		case path == "/api/v1/session" && r.Method == "GET":
			writeJSON(w, 200, map[string]string{"device_id": d.ID, "name": d.Name})
		case path == "/api/v1/session" && r.Method == "DELETE":
			http.SetCookie(w, sessionCookie(r, "", -1))
			writeJSON(w, 200, map[string]bool{"logged_out": true})
		case path == "/api/v1/pairing-codes" && r.Method == "POST":
			s.code = randomToken()
			s.codeExpires = time.Now().Add(10 * time.Minute)
			s.failures = map[string]int{}
			writeJSON(w, 201, map[string]any{"pairing_code": s.code, "expires_at": s.codeExpires.Unix()})
		case path == "/api/v1/pairing-codes" && r.Method == "GET":
			writeJSON(w, 200, map[string]any{"active": s.code != "" && time.Now().Before(s.codeExpires), "expires_at": s.codeExpires.Unix()})
		case path == "/api/v1/messages/sync" && r.Method == "POST":
			s.syncMessages(w, r, d)
		case path == "/api/v1/messages" && r.Method == "GET":
			s.listMessages(w, r)
		case (path == "/api/v1/messages/search" || path == "/api/v1/filter/quarantine") && r.Method == "GET":
			s.searchMessages(w, r)
		case strings.HasPrefix(path, "/api/v1/messages/") && r.Method == "GET":
			s.messageDetail(w, r)
		case path == "/api/v1/status" && r.Method == "GET":
			s.status(w, r)
		case path == "/api/v1/feedback/export" && r.Method == "POST":
			s.exportFeedback(w, r, d)
		case path == "/api/v1/feedback" && r.Method == "GET":
			s.listFeedback(w, r)
		case strings.HasPrefix(path, "/api/v1/feedback/") && r.Method == "PUT":
			s.reviewFeedback(w, r, d)
		case strings.HasPrefix(path, "/api/v1/messages/") && r.Method == "POST":
			s.operation(w, r)
		case path == "/api/v1/ai/settings" && r.Method == "GET":
			writeJSON(w, 200, s.publicLLM())
		case path == "/api/v1/ai/test" && r.Method == "POST":
			s.testLLM(w, r)
		case path == "/api/v1/ai/settings" && r.Method == "PUT":
			s.updateLLM(w, r)
		case path == "/api/v1/filter/rules" && r.Method == "GET":
			writeJSON(w, 200, s.store.Rules)
		case path == "/api/v1/filter/rules" && r.Method == "PUT":
			s.updateRules(w, r)
		case path == "/api/v1/devices" && r.Method == "GET":
			devices := []Device{}
			for _, device := range s.store.Devices {
				device.TokenHash = ""
				devices = append(devices, device)
			}
			sort.Slice(devices, func(i, j int) bool { return devices[i].ID < devices[j].ID })
			writeJSON(w, 200, devices)
		case strings.HasPrefix(path, "/api/v1/devices/") && r.Method == "DELETE":
			id := strings.TrimPrefix(path, "/api/v1/devices/")
			device, ok := s.store.Devices[id]
			if !ok {
				http.NotFound(w, r)
				return
			}
			before := s.snapshot()
			device.Active = false
			device.TokenHash = ""
			s.store.Devices[id] = device
			if s.commit(w, before) {
				for peer, owner := range s.peers {
					if owner == id {
						peer.Close()
						delete(s.peers, peer)
						delete(s.peerSignals, peer)
					}
				}
				writeJSON(w, 200, map[string]bool{"revoked": true})
			}
		default:
			http.NotFound(w, r)
		}
	})
	mux.Handle("/api/v1/", apiHandler)
	mux.Handle("/api/v2/", apiHandler)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		// Reverse proxies must overwrite X-Forwarded-Proto with the transport
		// they actually terminated; direct TLS is detected from r.TLS.
		if r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https" {
			w.Header().Set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
		}
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
		mux.ServeHTTP(w, r)
	})
}
func (s *Server) register(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID        string `json:"device_id"`
		Name      string `json:"name"`
		Key       string `json:"public_key"`
		Nonce     string `json:"nonce"`
		Code      string `json:"pairing_code"`
		Signature string `json:"signature"`
		E2EE      bool   `json:"e2ee,omitempty"`
	}
	if !readJSON(w, r, &req) {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.store.E2EEEnabled && !req.E2EE {
		writeJSON(w, 403, map[string]string{"error": "e2ee_required"})
		return
	}
	host, _, _ := net.SplitHostPort(r.RemoteAddr)
	if s.failures[host] >= 10 {
		writeJSON(w, 429, map[string]string{"error": "restart_pairing_session"})
		return
	}
	fail := func() { s.failures[host]++; writeJSON(w, 403, map[string]string{"error": "pairing_rejected"}) }
	if len(req.ID) < 16 || len(req.ID) > 100 || len(req.Name) > 64 || len(req.Nonce) < 16 || len(req.Nonce) > 128 ||
		s.code == "" || time.Now().After(s.codeExpires) || subtle.ConstantTimeCompare([]byte(hash(req.Code)), []byte(hash(s.code))) != 1 {
		fail()
		return
	}
	keyBytes, err := base64.StdEncoding.DecodeString(req.Key)
	if err != nil {
		fail()
		return
	}
	publicKey, err := x509.ParsePKIXPublicKey(keyBytes)
	if err != nil {
		fail()
		return
	}
	key, ok := publicKey.(*ecdsa.PublicKey)
	if !ok || key.Curve != elliptic.P256() {
		fail()
		return
	}
	sig, err := base64.StdEncoding.DecodeString(req.Signature)
	canonical := req.ID + "\n" + req.Key + "\n" + req.Nonce + "\n" + req.Code
	if req.E2EE {
		canonical += "\ne2ee-v1"
	}
	digest := sha256.Sum256([]byte(canonical))
	if err != nil || !ecdsa.VerifyASN1(key, digest[:], sig) {
		fail()
		return
	}
	if old, exists := s.store.Devices[req.ID]; exists && old.PublicKey != req.Key {
		fail()
		return
	}
	token := randomToken()
	before := s.snapshot()
	if req.E2EE {
		s.store.E2EEEnabled = true
	}
	s.store.Devices[req.ID] = Device{ID: req.ID, Name: req.Name, PublicKey: req.Key, E2EE: req.E2EE, TokenHash: hash(token), Active: true, Expires: time.Now().Add(90 * 24 * time.Hour).Unix()}
	if s.commit(w, before) {
		s.code = ""
		writeJSON(w, 201, map[string]string{"token": token, "device_id": req.ID})
	}
}
func sameUploadedMessage(existing, incoming Message, device string) bool {
	return existing.Device == device && existing.Sender == incoming.Sender && existing.Body == incoming.Body && existing.Received == incoming.Received && existing.Subscription == incoming.Subscription
}
func (s *Server) syncMessages(w http.ResponseWriter, r *http.Request, d Device) {
	if s.store.E2EEEnabled || d.E2EE {
		writeJSON(w, 403, map[string]string{"error": "e2ee_required"})
		return
	}
	var req struct {
		Messages []Message `json:"messages"`
	}
	// Fifty 4096-rune bodies can exceed 2 MiB with JSON surrogate-pair escapes.
	if !readJSONLimit(w, r, &req, 3*1024*1024) {
		return
	}
	if len(req.Messages) > 50 || len(req.Messages) == 0 {
		writeJSON(w, 400, map[string]string{"error": "batch_size"})
		return
	}
	for _, m := range req.Messages {
		if len(m.ID) < 16 || len(m.ID) > 100 || len(m.Body) == 0 || len([]rune(m.Body)) > 4096 || len([]rune(m.Sender)) > 64 || m.Received <= 0 {
			writeJSON(w, 422, map[string]string{"error": "message_contract"})
			return
		}
	}
	// Capture immutable model settings, then perform network I/O outside the store lock.
	worker := s.classificationWorker()
	todo := []Message{}
	seen := map[string]Message{}
	for _, incoming := range req.Messages {
		old, exists := s.store.Messages[s.store.messageID(incoming.ID)]
		prior, duplicate := seen[incoming.ID]
		if (exists && !sameUploadedMessage(old, incoming, d.ID)) || (duplicate && !sameUploadedMessage(prior, incoming, d.ID)) {
			writeJSON(w, 409, map[string]string{"error": "id_conflict"})
			return
		}
		seen[incoming.ID] = Message{Sender: incoming.Sender, Body: incoming.Body, Received: incoming.Received, Subscription: incoming.Subscription, Device: d.ID}
		if (!exists || !old.Classified) && !duplicate {
			todo = append(todo, incoming)
		}
	}
	s.mu.Unlock()
	results := worker.classifyBatch(r.Context(), todo)
	s.mu.Lock()
	// Revocation or configuration changes while the model ran must take effect.
	if s.store.E2EEEnabled {
		writeJSON(w, 403, map[string]string{"error": "e2ee_only"})
		return
	}
	if current, ok := s.auth(r); !ok || current.ID != d.ID {
		writeJSON(w, 401, map[string]string{"error": "pairing_required"})
		return
	}
	if !s.sameClassificationSettings(worker) {
		results = nil
	}
	before := s.snapshot()
	type syncAcknowledgement struct {
		Message
		CanonicalID string `json:"canonical_message_id,omitempty"`
	}
	result := []syncAcknowledgement{}
	for _, incoming := range req.Messages {
		m, exists := s.store.Messages[s.store.messageID(incoming.ID)]
		if exists && !sameUploadedMessage(m, incoming, d.ID) {
			s.rollback(before)
			writeJSON(w, 409, map[string]string{"error": "id_conflict"})
			return
		}
		if !exists {
			m = Message{ID: incoming.ID, Sender: incoming.Sender, Body: incoming.Body, Received: incoming.Received, Subscription: incoming.Subscription, Slot: incoming.Slot, Device: d.ID}
			// A replay with a different transport ID still maps to one server message.
			for _, old := range s.store.Messages {
				if old.Device == d.ID && old.Sender == m.Sender && old.Body == m.Body && old.Received == m.Received && old.Subscription == m.Subscription {
					m = old
					exists = true
					break
				}
			}
		}
		if exists && incoming.ID != m.ID {
			if s.store.MessageAliases == nil {
				s.store.MessageAliases = map[string]string{}
			}
			s.store.MessageAliases[incoming.ID] = m.ID
		}
		if !exists || !m.Classified {
			classified, ok := results[incoming.ID]
			c := classified.Classification
			// A retry during an upstream outage is still an ACK of the same
			// durable message, not a new revision or a reversal of user restore.
			if !exists || ok {
				m = applyPolicy(m, c, ok, s.store.Rules)
				s.store.Revision++
				m.Revision = s.store.Revision
				s.store.Messages[m.ID] = m
			}
		}
		// ACK the caller's id while preserving server identity for subsequent pulls.
		ack := syncAcknowledgement{Message: m}
		if incoming.ID != m.ID {
			ack.CanonicalID = m.ID
		}
		ack.ID = incoming.ID
		result = append(result, ack)
	}
	if s.commit(w, before) {
		writeJSON(w, 200, map[string]any{"messages": result})
		s.broadcast()
	}
}
func (s *Server) listMessages(w http.ResponseWriter, r *http.Request) {
	cursor, err := strconv.ParseInt(defaultString(r.URL.Query().Get("cursor"), "0"), 10, 64)
	if err != nil || cursor < 0 {
		writeJSON(w, 400, map[string]string{"error": "cursor"})
		return
	}
	limit, _ := strconv.Atoi(defaultString(r.URL.Query().Get("limit"), "50"))
	if limit < 1 || limit > 50 {
		limit = 50
	}
	rows := []Message{}
	for _, m := range s.store.Messages {
		if m.Revision > cursor {
			rows = append(rows, m)
		}
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].Revision < rows[j].Revision })
	more := len(rows) > limit
	if more {
		rows = rows[:limit]
	}
	if len(rows) > 0 {
		cursor = rows[len(rows)-1].Revision
	}
	writeJSON(w, 200, map[string]any{"messages": rows, "cursor": cursor, "has_more": more})
}
func defaultString(v, def string) string {
	if v == "" {
		return def
	}
	return v
}
func (s *Server) operation(w http.ResponseWriter, r *http.Request) {
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/api/v1/messages/"), "/")
	if len(parts) != 2 {
		http.NotFound(w, r)
		return
	}
	m, ok := s.store.Messages[s.store.messageID(parts[0])]
	if !ok {
		http.NotFound(w, r)
		return
	}
	var req struct {
		ID       string `json:"operation_id"`
		Category string `json:"corrected_category"`
	}
	if !readJSON(w, r, &req) {
		return
	}
	if len(req.ID) < 16 || len(req.ID) > 100 {
		writeJSON(w, 422, map[string]string{"error": "operation_id"})
		return
	}
	kind := parts[1]
	if kind != "archive" && kind != "unarchive" && kind != "restore" && kind != "feedback" {
		http.NotFound(w, r)
		return
	}
	if old, exists := s.store.MessageOperations[req.ID]; exists {
		if old.MessageID != m.ID || old.Kind != kind {
			writeJSON(w, 409, map[string]string{"error": "operation_conflict"})
			return
		}
		// Return the latest state without reapplying an older user intention.
		writeJSON(w, 200, m)
		return
	}
	if old, exists := s.store.Feedback[req.ID]; exists {
		if kind != "feedback" || old.MessageID != m.ID || old.Category != req.Category {
			writeJSON(w, 409, map[string]string{"error": "operation_conflict"})
			return
		}
		writeJSON(w, 200, map[string]string{"status": old.Status})
		return
	}
	before := s.snapshot()
	switch kind {
	case "archive", "unarchive", "restore":
		changed := false
		if kind == "restore" {
			changed = !m.Restored || m.Archived || m.Action != "allow" || m.Reason != "用户恢复"
			m.Action, m.Reason, m.Restored, m.Archived = "allow", "用户恢复", true, false
		} else {
			archived := kind == "archive"
			changed = m.Archived != archived
			m.Archived = archived
		}
		if changed {
			s.store.Revision++
			m.Revision = s.store.Revision
			s.store.Messages[m.ID] = m
		}
		if s.store.MessageOperations == nil {
			s.store.MessageOperations = map[string]MessageOperation{}
		}
		// Persist no-op receipts too: a later retry must not undo a newer change.
		s.store.MessageOperations[req.ID] = MessageOperation{MessageID: m.ID, Kind: kind}
		if s.commit(w, before) {
			writeJSON(w, 200, m)
			if changed {
				s.broadcast()
			}
		}
	case "feedback":
		if !categories[req.Category] {
			writeJSON(w, 422, map[string]string{"error": "category"})
			return
		}
		s.store.Feedback[req.ID] = Feedback{ID: req.ID, MessageID: m.ID, Category: req.Category, Status: "pending_review", Predicted: m.Category, Model: m.Model}
		if s.commit(w, before) {
			writeJSON(w, 200, map[string]string{"status": "pending_review"})
			s.broadcast()
		}
	default:
		http.NotFound(w, r)
	}
}
func (s *Server) updateRules(w http.ResponseWriter, r *http.Request) {
	var rules Rules
	if !readJSON(w, r, &rules) {
		return
	}
	if (rules.Mode != "classify" && rules.Mode != "filter" && rules.Mode != "block") || math.IsNaN(rules.Threshold) || rules.Threshold < 0.8 || rules.Threshold > 1 || len(rules.Whitelist) > 500 || len(rules.Blacklist) > 500 {
		writeJSON(w, 422, map[string]string{"error": "rules_contract"})
		return
	}
	for _, list := range [][]string{rules.Whitelist, rules.Blacklist} {
		for _, entry := range list {
			if len(entry) > 128 {
				writeJSON(w, 422, map[string]string{"error": "sender_length"})
				return
			}
		}
	}
	if rules.Whitelist == nil {
		rules.Whitelist = []string{}
	}
	if rules.Blacklist == nil {
		rules.Blacklist = []string{}
	}
	before := s.snapshot()
	s.store.Rules = rules
	if s.commit(w, before) {
		writeJSON(w, 200, rules)
		s.broadcast()
	}
}
func (s *Server) websocket(w http.ResponseWriter, r *http.Request, d Device) {
	up := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return r.Header.Get("Origin") == "" || sameOrigin(r) }, HandshakeTimeout: 5 * time.Second}
	conn, err := up.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	s.peers[conn] = d.ID
	signal := make(chan struct{}, 1)
	s.peerSignals[conn] = signal
	done := make(chan struct{})
	go func() {
		defer func() {
			s.mu.Lock()
			delete(s.peers, conn)
			delete(s.peerSignals, conn)
			s.mu.Unlock()
			close(done)
			conn.Close()
		}()
		conn.SetReadLimit(1024)
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}()
	// Exactly one writer per connection. Slow clients never hold the store lock.
	go func() {
		for {
			select {
			case <-done:
				return
			case <-signal:
				_ = conn.SetWriteDeadline(time.Now().Add(time.Second))
				if conn.WriteJSON(map[string]string{"event": "changed"}) != nil {
					conn.Close()
					return
				}
			}
		}
	}()
}

// Called under mu; coalesce notifications because clients fetch from their cursor.
func (s *Server) broadcast() {
	for c, id := range s.peers {
		device, ok := s.store.Devices[id]
		if !ok || !device.Active || device.Expires <= time.Now().Unix() {
			c.Close()
			delete(s.peers, c)
			delete(s.peerSignals, c)
			continue
		}
		select {
		case s.peerSignals[c] <- struct{}{}:
		default:
		}
	}
}

func main() {
	addr := flag.String("listen", "127.0.0.1:8787", "HTTP bind (use HTTPS reverse proxy)")
	data := flag.String("data", "data/privrelay.enc", "encrypted single-owner MVP store")
	tlsCert := flag.String("tls-cert", "", "TLS certificate PEM; requires -tls-key")
	tlsKey := flag.String("tls-key", "", "TLS private key PEM; requires -tls-cert")
	classifier := flag.String("classifier", os.Getenv("CLASSIFIER_URL"), "PrivateSMS classifier base URL")
	webDir := flag.String("web", "", "optional built frontend directory (disabled by default)")
	maintenance := flag.String("maintenance", "", "offline backup, restore or rotate-key")
	output := flag.String("output", "", "new private destination directory for maintenance")
	flag.Parse()
	if (*tlsCert == "") != (*tlsKey == "") {
		log.Fatal("TLS requires both -tls-cert and -tls-key")
	}
	if *maintenance != "" {
		if err := maintainStore(*maintenance, *data, *output); err != nil {
			log.Fatal("maintenance failed: ", err)
		}
		fmt.Println("Maintenance completed; original source preserved.")
		return
	}
	if err := os.MkdirAll(filepath.Dir(*data), 0700); err != nil {
		log.Fatal("cannot create store directory")
	}
	storeLock, err := lockStore(*data)
	if err != nil {
		log.Fatal("data store is already in use or cannot be locked")
	}
	defer storeLock.Close()
	store, err := openStore(*data)
	if err != nil {
		log.Fatal("cannot open protected data store")
	}
	s := newServer(store, *classifier)
	s.webDir = *webDir
	s.classifierKey = os.Getenv("CLASSIFIER_API_KEY")
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	backgroundDone := make(chan struct{})
	go func() {
		defer close(backgroundDone)
		ticker := time.NewTicker(time.Minute)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				s.refreshClassifications()
			}
		}
	}()
	fmt.Printf("PrivRelay listening on %s\nOne-time pairing code (10 minutes): %s\n", *addr, s.code)
	server := &http.Server{Addr: *addr, Handler: s.handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 * 1024}
	if *tlsCert != "" {
		server.TLSConfig = &tls.Config{MinVersion: tls.VersionTLS12}
		fmt.Println("TLS enabled (minimum TLS 1.2)")
	}
	shutdownDone := make(chan struct{})
	go func() {
		defer close(shutdownDone)
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
		s.mu.Lock()
		for peer := range s.peers {
			_ = peer.Close()
		}
		s.mu.Unlock()
	}()
	var serveErr error
	if *tlsCert != "" {
		serveErr = server.ListenAndServeTLS(*tlsCert, *tlsKey)
	} else {
		serveErr = server.ListenAndServe()
	}
	stop()
	<-shutdownDone
	<-backgroundDone
	if serveErr != nil && serveErr != http.ErrServerClosed {
		log.Fatal("HTTP service stopped: ", serveErr)
	}
}
