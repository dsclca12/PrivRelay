package main

import (
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"
)

func validReviewStatus(status string) bool {
	return status == "pending_review" || status == "approved" || status == "rejected"
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
	counts := map[string]int{"pending_review": 0, "approved": 0, "rejected": 0}
	corrections := map[string]int{}
	for _, f := range s.store.Feedback {
		// Older snapshots predate prediction provenance; fall back for display only.
		if f.Predicted == "" {
			f.Predicted = s.store.Messages[f.MessageID].Category
			f.Model = s.store.Messages[f.MessageID].Model
		}
		counts[f.Status]++
		if f.Status == "approved" {
			corrections[f.Predicted+"→"+f.Category]++
		}
		if status == "" || f.Status == status {
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
