package main

import (
	"context"
	"reflect"
	"slices"
	"sort"
	"time"
)

// Only these immutable settings and the concurrent-safe HTTP client cross the lock boundary.
func (s *Server) classificationWorker() *Server {
	rules := s.store.Rules
	rules.Whitelist = append([]string(nil), rules.Whitelist...)
	rules.Blacklist = append([]string(nil), rules.Blacklist...)
	return &Server{store: &Store{LLM: s.store.LLM, Rules: rules}, classifier: s.classifier, classifierKey: s.classifierKey, client: s.client}
}
func (s *Server) sameClassificationSettings(worker *Server) bool {
	a, b := s.store.Rules, worker.store.Rules
	return s.store.LLM == worker.store.LLM && a.Mode == b.Mode && a.Threshold == b.Threshold && slices.Equal(a.Whitelist, b.Whitelist) && slices.Equal(a.Blacklist, b.Blacklist)
}

type classificationResult struct{ Classification Classification }

func (s *Server) classifyBatch(parent context.Context, messages []Message) map[string]classificationResult {
	ctx, cancel := context.WithTimeout(parent, 8*time.Second)
	defer cancel()
	results := map[string]classificationResult{}
	for _, m := range messages {
		s.retryCursor = m.ID
		c, ok := s.classifyContext(ctx, m)
		if !ok {
			break
		}
		results[m.ID] = classificationResult{c}
	}
	return results
}

// Round-robin retry prevents a persistently uncertain message starving later records.
func (s *Server) refreshClassifications() {
	s.mu.Lock()
	worker := s.classificationWorker()
	pending := []Message{}
	for _, m := range s.store.Messages {
		if !m.Classified || m.LLMPending {
			pending = append(pending, m)
		}
	}
	sort.Slice(pending, func(i, j int) bool { return pending[i].ID < pending[j].ID })
	if len(pending) > 0 {
		start := sort.Search(len(pending), func(i int) bool { return pending[i].ID > s.retryCursor })
		pending = append(pending[start:], pending[:start]...)
	}
	if len(pending) > 50 {
		pending = pending[:50]
	}
	s.mu.Unlock()
	results := worker.classifyBatch(context.Background(), pending)
	s.mu.Lock()
	defer s.mu.Unlock()
	if worker.retryCursor != "" {
		s.retryCursor = worker.retryCursor
	}
	if !s.sameClassificationSettings(worker) || len(results) == 0 {
		return
	}
	before := s.snapshot()
	changed := false
	for _, previous := range pending {
		result, ok := results[previous.ID]
		current, exists := s.store.Messages[previous.ID]
		// Never overwrite a concurrent restore, archive, deletion or newer classification.
		if !ok || !exists || current.Revision != previous.Revision {
			continue
		}
		m := applyPolicy(current, result.Classification, true, s.store.Rules)
		if reflect.DeepEqual(current, m) {
			continue
		}
		s.store.Revision++
		m.Revision = s.store.Revision
		s.store.Messages[m.ID] = m
		changed = true
	}
	if changed {
		if s.store.save() != nil {
			s.rollback(before)
		} else {
			s.broadcast()
		}
	}
}
