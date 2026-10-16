package timeparse

import (
	"fmt"
	"strconv"
	"strings"
)

// ParseDuration parses human-friendly durations such as "90s", "15m" or "2h" into seconds.
func ParseDuration(text string) (int, error) {
	text = strings.TrimSpace(text)
	if len(text) < 2 {
		return 0, fmt.Errorf("invalid duration %q", text)
	}
	value, err := strconv.Atoi(text[:len(text)-1])
	if err != nil || value < 0 {
		return 0, fmt.Errorf("invalid duration %q", text)
	}
	switch text[len(text)-1] {
	case 's':
		return value, nil
	case 'm':
		return value * 60, nil
	case 'h':
		return value * 3600, nil
	}
	return 0, fmt.Errorf("unknown unit in %q", text)
}
