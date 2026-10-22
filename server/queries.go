package main

import (
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Search pagination is deliberately separate from Android's revision cursor.
// A sync cursor must always observe every change, including restores.
func (s *Server) searchMessages(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	category, action, device := q.Get("category"), q.Get("action"), q.Get("device_id")
	if r.URL.Path == "/api/v1/filter/quarantine" {
		action = "quarantine"
	}
	limit, err := strconv.Atoi(defaultString(q.Get("limit"), "50"))
	offset, offsetErr := strconv.Atoi(defaultString(q.Get("offset"), "0"))
	if err != nil || offsetErr != nil || offset < 0 || limit < 1 || limit > 50 ||
		(category != "" && !categories[category]) || (action != "" && action != "allow" && action != "quarantine") || len(q.Get("q")) > 512 {
		writeJSON(w, 400, map[string]string{"error": "query_contract"})
		return
	}
	archived := q.Get("archived")
	if archived != "" && archived != "true" && archived != "false" && archived != "all" {
		writeJSON(w, 400, map[string]string{"error": "query_contract"})
		return
	}
	needle := strings.ToLower(q.Get("q"))
	rows := []Message{}
	for _, m := range s.store.Messages {
		// Quarantine always remains visible, including archived quarantine records.
		if r.URL.Path != "/api/v1/filter/quarantine" && archived != "all" && m.Archived != (archived == "true") {
			continue
		}
		if category != "" && m.Category != category || action != "" && m.Action != action || device != "" && m.Device != device {
			continue
		}
		if needle != "" && !strings.Contains(strings.ToLower(m.Sender), needle) && !strings.Contains(strings.ToLower(m.Body), needle) {
			continue
		}
		rows = append(rows, m)
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Received == rows[j].Received {
			return rows[i].ID < rows[j].ID
		}
		return rows[i].Received > rows[j].Received
	})
	total := len(rows)
	if offset > total {
		offset = total
	}
	end := offset + min(limit, total-offset)
	writeJSON(w, 200, map[string]any{"messages": rows[offset:end], "total": total, "offset": offset, "has_more": end < total})
}

func (s *Server) messageDetail(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/v1/messages/")
	m, ok := s.store.Messages[s.store.messageID(id)]
	if !ok {
		writeJSON(w, 404, map[string]string{"error": "message_not_found"})
		return
	}
	writeJSON(w, 200, m)
}

func (s *Server) status(w http.ResponseWriter, r *http.Request) {
	counts := map[string]int{}
	quarantined, restored, pending, active, online := 0, 0, 0, 0, 0
	reasons := map[string]int{}
	for _, m := range s.store.Messages {
		counts[m.Category]++
		if m.Action == "quarantine" {
			quarantined++
			reasons[m.Reason]++
		}
		if m.Restored {
			restored++
		}
		if !m.Classified {
			pending++
		}
	}
	now := time.Now().Unix()
	connected := map[string]bool{}
	for _, id := range s.peers {
		connected[id] = true
	}
	for _, d := range s.store.Devices {
		if d.Active && d.Expires > now {
			active++
			if connected[d.ID] {
				online++
			}
		}
	}
	pendingLLM := 0
	for _, m := range s.store.Messages {
		if m.LLMPending {
			pendingLLM++
		}
	}
	pendingFeedback := 0
	for _, f := range s.store.Feedback {
		if f.Status == "pending_review" {
			pendingFeedback++
		}
	}
	writeJSON(w, 200, map[string]any{"messages": len(s.store.Messages) + len(s.store.EncryptedMessages), "encrypted_messages": len(s.store.EncryptedMessages), "e2ee_enabled": s.store.E2EEEnabled, "quarantined": quarantined, "restored": restored, "quarantine_reasons": reasons,
		"pending_classification": pending, "categories": counts, "authorized_devices": active,
		"connected_devices": online, "pending_feedback": pendingFeedback, "revision": s.store.Revision,
		"llm_mode": defaultString(s.store.LLM.Mode, "disabled"), "pending_llm_review": pendingLLM, "classifier_configured": s.classifier != "", "server_time": now})
}
