package main

import (
	"encoding/base64"
	"net/http"
	"sort"
	"strconv"
)

type encryptedBatch struct {
	Messages []EncryptedMessage `json:"messages"`
}

func (s *Server) migrateLegacyMessages(w http.ResponseWriter, r *http.Request, d Device) {
	if !d.E2EE {
		writeJSON(w, 403, map[string]string{"error": "e2ee_required"})
		return
	}
	var req struct {
		IDs      []string `json:"message_ids"`
		Complete bool     `json:"complete"`
	}
	if !readJSON(w, r, &req) {
		return
	}
	if (!req.Complete && (len(req.IDs) == 0 || len(req.IDs) > 50)) || len(req.IDs) > 50 {
		writeJSON(w, 400, map[string]string{"error": "batch_size"})
		return
	}
	before := s.snapshot()
	deleted := 0
	if req.Complete {
		deleted = len(s.store.Messages)
		s.store.Messages = map[string]Message{}
		s.store.MessageOperations = map[string]MessageOperation{}
		s.store.Feedback = map[string]Feedback{}
		s.store.LegacyPurged = true
	}
	for _, id := range req.IDs {
		legacy, exists := s.store.Messages[id]
		sealed, uploaded := s.store.EncryptedMessages[id]
		if exists && uploaded && legacy.Device == d.ID && sealed.Device == d.ID {
			delete(s.store.Messages, id)
			delete(s.store.MessageOperations, id)
			for operationID, feedback := range s.store.Feedback {
				if feedback.MessageID == id {
					delete(s.store.Feedback, operationID)
				}
			}
			deleted++
		}
	}
	if s.commit(w, before) {
		writeJSON(w, 200, map[string]int{"deleted": deleted})
		s.broadcast()
	}
}

// syncEncryptedMessages stores ciphertext without parsing or classifying it.
// The ciphertext envelope is authenticated and decrypted only by clients.
func (s *Server) syncEncryptedMessages(w http.ResponseWriter, r *http.Request, d Device) {
	if !d.E2EE {
		writeJSON(w, 403, map[string]string{"error": "e2ee_required"})
		return
	}
	var req encryptedBatch
	if !readJSONLimit(w, r, &req, 5*1024*1024) {
		return
	}
	if len(req.Messages) == 0 || len(req.Messages) > 50 {
		writeJSON(w, 400, map[string]string{"error": "batch_size"})
		return
	}
	seen := map[string]EncryptedMessage{}
	for _, m := range req.Messages {
		if len(m.ID) < 16 || len(m.ID) > 100 || m.Received <= 0 || len(m.Ciphertext) > 128*1024 {
			writeJSON(w, 422, map[string]string{"error": "encrypted_message_contract"})
			return
		}
		blob, err := base64.RawURLEncoding.DecodeString(m.Ciphertext)
		if err != nil || len(blob) < 29 || len(blob) > 96*1024 {
			writeJSON(w, 422, map[string]string{"error": "encrypted_message_contract"})
			return
		}
		if previous, ok := seen[m.ID]; ok && previous.Ciphertext != m.Ciphertext {
			writeJSON(w, 409, map[string]string{"error": "id_conflict"})
			return
		}
		seen[m.ID] = m
	}

	before := s.snapshot()
	if s.store.EncryptedMessages == nil {
		s.store.EncryptedMessages = map[string]EncryptedMessage{}
	}
	acks := make([]EncryptedMessage, 0, len(req.Messages))
	for _, incoming := range req.Messages {
		if existing, ok := s.store.EncryptedMessages[incoming.ID]; ok {
			if existing.Received != incoming.Received {
				s.rollback(before)
				writeJSON(w, 409, map[string]string{"error": "id_conflict"})
				return
			}
			if existing.Ciphertext != incoming.Ciphertext {
				s.store.Revision++
				existing.Ciphertext = incoming.Ciphertext
				existing.Revision = s.store.Revision
				s.store.EncryptedMessages[incoming.ID] = existing
			}
			acks = append(acks, existing)
			continue
		}
		s.store.Revision++
		incoming.Device = d.ID
		incoming.Revision = s.store.Revision
		s.store.EncryptedMessages[incoming.ID] = incoming
		acks = append(acks, incoming)
	}
	if s.commit(w, before) {
		writeJSON(w, 200, map[string]any{"messages": acks})
		s.broadcast()
	}
}

func (s *Server) listEncryptedMessages(w http.ResponseWriter, r *http.Request) {
	cursor, err := strconv.ParseInt(defaultString(r.URL.Query().Get("cursor"), "0"), 10, 64)
	if err != nil || cursor < 0 {
		writeJSON(w, 400, map[string]string{"error": "cursor"})
		return
	}
	limit, err := strconv.Atoi(defaultString(r.URL.Query().Get("limit"), "50"))
	if err != nil || limit < 1 || limit > 50 {
		writeJSON(w, 400, map[string]string{"error": "limit"})
		return
	}
	rows := make([]EncryptedMessage, 0)
	for _, m := range s.store.EncryptedMessages {
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
