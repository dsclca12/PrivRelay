package main

import (
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"
)

func validReviewStatus(status string) bool {
	return status == "pending_review" || status == "approved" || status == "rejected" || status == "withdrawn"
}

func (s *Server) listFeedback(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	status := q.Get("status")
	limit, err := strconv.Atoi(defaultString(q.Get("limit"), "20"))
	offset, offsetErr := strconv.Atoi(defaultString(q.Get("offset"), "0"))
	if err != nil || offsetErr != nil || limit < 1 || limit > 50 || offset < 0 || status != "" && !validReviewStatus(status) {
		writeJSON(w, 400, map[string]string{"error": "query_contract"})
		return
	}
	rows := []Feedback{}
	counts := map[string]int{"pending_review": 0, "approved": 0, "rejected": 0, "withdrawn": 0}
	corrections := map[string]int{}
	for _, f := range s.store.Feedback {
		// Older snapshots predate prediction provenance; fall back for display only.
		if f.Predicted == "" {
			f.Predicted = s.store.Messages[f.MessageID].Category
			f.Model = s.store.Messages[f.MessageID].Model
		}
		statusValue := f.Status
		if f.WithdrawnAt != 0 {
			statusValue = "withdrawn"
		}
		counts[statusValue]++
		if statusValue == "approved" {
			corrections[f.Predicted+"→"+f.Category]++
		}
		f.Status = statusValue
		if status == "" || statusValue == status {
			rows = append(rows, f)
		}
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].ID < rows[j].ID })
	total := len(rows)
	if offset > total {
		offset = total
	}
	end := offset + min(limit, total-offset)
	writeJSON(w, 200, map[string]any{"feedback": rows[offset:end], "total": total, "offset": offset,
		"has_more": end < total, "counts": counts, "corrections": corrections})
}

func (s *Server) reviewFeedback(w http.ResponseWriter, r *http.Request, d Device) {
	id := strings.TrimPrefix(r.URL.Path, "/api/v1/feedback/")
	f, ok := s.store.Feedback[id]
	if !ok {
		writeJSON(w, 404, map[string]string{"error": "feedback_not_found"})
		return
	}
	if f.WithdrawnAt != 0 {
		writeJSON(w, 409, map[string]string{"error": "consent_withdrawn"})
		return
	}
	var req struct {
		Status string `json:"review_status"`
	}
	if !readJSON(w, r, &req) {
		return
	}
	if req.Status != "approved" && req.Status != "rejected" {
		writeJSON(w, 422, map[string]string{"error": "review_status"})
		return
	}
	// A retry cannot reopen or reverse a review performed by another device.
	if f.Status != "pending_review" {
		if f.Status != req.Status {
			writeJSON(w, 409, map[string]string{"error": "operation_conflict"})
			return
		}
		writeJSON(w, 200, f)
		return
	}
	before := s.snapshot()
	f.Status, f.ReviewedBy, f.ReviewedAt = req.Status, d.ID, time.Now().Unix()
	s.store.Feedback[id] = f
	if s.commit(w, before) {
		writeJSON(w, 200, f)
		s.broadcast()
	}
}

// Withdrawal is a durable tombstone: the correction can no longer be reviewed
// or included in future exports, while its operation ID prevents replay from
// restoring withdrawn data.
func (s *Server) withdrawFeedback(w http.ResponseWriter, r *http.Request, d Device) {
	id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/api/v1/feedback/"), "/withdraw")
	f, ok := s.store.Feedback[id]
	if !ok {
		writeJSON(w, 404, map[string]string{"error": "feedback_not_found"})
		return
	}
	if f.WithdrawnAt != 0 {
		writeJSON(w, 200, map[string]string{"status": "withdrawn"})
		return
	}
	before := s.snapshot()
	f.WithdrawnAt, f.WithdrawnBy = time.Now().Unix(), d.ID
	s.store.Feedback[id] = f
	if s.commit(w, before) {
		writeJSON(w, 200, map[string]string{"status": "withdrawn"})
		s.broadcast()
	}
}

// Export one bounded page at a time; approval alone never authorizes disclosure.
func (s *Server) exportFeedback(w http.ResponseWriter, r *http.Request, d Device) {
	var req struct {
		Consent     bool   `json:"consent"`
		Purpose     string `json:"purpose"`
		IncludeText bool   `json:"include_text"`
		Offset      int    `json:"offset"`
		Limit       int    `json:"limit"`
	}
	if !readJSON(w, r, &req) {
		return
	}
	if !req.Consent || (req.Purpose != "evaluation" && req.Purpose != "training") || req.Offset < 0 || req.Limit < 1 || req.Limit > 100 {
		writeJSON(w, 422, map[string]string{"error": "export_consent_required"})
		return
	}
	rows := []Feedback{}
	for _, f := range s.store.Feedback {
		if f.Status == "approved" && f.WithdrawnAt == 0 {
			rows = append(rows, f)
		}
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].ID < rows[j].ID })
	start := min(req.Offset, len(rows))
	end := min(start+req.Limit, len(rows))
	samples := []map[string]any{}
	for _, f := range rows[start:end] {
		row := map[string]any{"operation_id": f.ID, "message_id": f.MessageID, "label": f.Category, "predicted_category": f.Predicted, "model_version": f.Model, "reviewed_at": f.ReviewedAt}
		if req.IncludeText {
			m, ok := s.store.Messages[f.MessageID]
			if !ok {
				continue
			}
			row["text"] = m.Body
			row["sender"] = m.Sender
		}
		samples = append(samples, row)
	}
	// Record consent metadata only; never duplicate message text or credentials.
	before := s.snapshot()
	exportID := randomToken()
	s.store.Exports = append(s.store.Exports, ExportAudit{ExportID: exportID, Device: d.ID, At: time.Now().Unix(), Purpose: req.Purpose, IncludeText: req.IncludeText, Count: len(samples)})
	if len(s.store.Exports) > 1000 {
		s.store.Exports = s.store.Exports[len(s.store.Exports)-1000:]
	}
	if s.commit(w, before) {
		writeJSON(w, 200, map[string]any{"schema_version": 1, "export_id": exportID, "consent": true, "samples": samples, "total": len(rows), "offset": start, "has_more": end < len(rows), "purpose": req.Purpose, "include_text": req.IncludeText})
	}
}
