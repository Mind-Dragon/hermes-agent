package core

import (
	"regexp"
	"strings"
)

// Entity represents a business entity from search results
type Entity struct {
	ID     string
	Name   string
	Type   string
	Status string
}

// ParseEntitySearchResults parses HTML search results and extracts entity information.
// It handles multiple formats:
// 1. Standard format with "result-row" class and "col-type"/"col-status" classes
// 2. Delaware ASP.NET format with table ID "tblResults"
func ParseEntitySearchResults(html string) ([]Entity, error) {
	var entities []Entity

	// First, try the standard format with result-row class
	entities = parseStandardFormat(html)

	// If no entities found, try Delaware ASP.NET format
	if len(entities) == 0 {
		entities = parseDelawareFormat(html)
	}

	return entities, nil
}

// parseStandardFormat handles the standard format with class="result-row"
// and columns with classes "col-type", "col-status"
func parseStandardFormat(html string) []Entity {
	var entities []Entity

	// Match table rows containing entity data
	// Pattern: <tr> with entity name in <a> tag, type and status in <td>
	rowPattern := regexp.MustCompile(`(?s)<tr[^>]*class="[^"]*result-row[^"]*"[^>]*>(.*?)</tr>`)
	rows := rowPattern.FindAllStringSubmatch(html, -1)

	for _, row := range rows {
		if len(row) < 2 {
			continue
		}
		tr := row[1]

		// Extract entity name from <a> tag
		namePattern := regexp.MustCompile(`<a[^>]*href="[^"]*"[^>]*>([^<]+)</a>`)
		nameMatch := namePattern.FindStringSubmatch(tr)
		name := ""
		if len(nameMatch) > 1 {
			name = strings.TrimSpace(nameMatch[1])
		}

		// Extract entity ID from href
		idPattern := regexp.MustCompile(`<a[^>]*href="[^"]*entityID=([^"&]+)[^"]*"`)
		idMatch := idPattern.FindStringSubmatch(tr)
		id := ""
		if len(idMatch) > 1 {
			id = strings.TrimSpace(idMatch[1])
		}

		// Extract entity type
		typePattern := regexp.MustCompile(`<td[^>]*class="[^"]*col-type[^"]*"[^>]*>([^<]+)</td>`)
		typeMatch := typePattern.FindStringSubmatch(tr)
		entityType := ""
		if len(typeMatch) > 1 {
			entityType = strings.TrimSpace(typeMatch[1])
		}

		// Extract status
		statusPattern := regexp.MustCompile(`<td[^>]*class="[^"]*col-status[^"]*"[^>]*>\s*<span[^>]*class="status-([^"]*)"[^>]*>`)
		statusMatch := statusPattern.FindStringSubmatch(tr)
		status := ""
		if len(statusMatch) > 1 {
			status = strings.TrimSpace(statusMatch[1])
		}

		if name != "" {
			entities = append(entities, Entity{
				ID:     id,
				Name:   name,
				Type:   entityType,
				Status: status,
			})
		}
	}

	// If no rows matched, try simpler pattern for fixture compatibility
	if len(entities) == 0 {
		simplePattern := regexp.MustCompile(`<tr>\s*<td><a[^>]*>([^<]+)</a></td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>`)
		matches := simplePattern.FindAllStringSubmatch(html, -1)
		for _, m := range matches {
			if len(m) >= 4 {
				entities = append(entities, Entity{
					Name:   strings.TrimSpace(m[1]),
					Type:   strings.TrimSpace(m[2]),
					Status: strings.TrimSpace(m[3]),
				})
			}
		}
	}

	return entities
}

// parseDelawareFormat handles Delaware's ASP.NET table format
// Table has ID "tblResults" with no classes on rows/columns
func parseDelawareFormat(html string) []Entity {
	var entities []Entity

	// Find the table with ID tblResults
	tablePattern := regexp.MustCompile(`(?s)<table[^>]*id="tblResults"[^>]*>(.*?)</table>`)
	tableMatch := tablePattern.FindStringSubmatch(html)
	if len(tableMatch) < 2 {
		return entities
	}
	tableContent := tableMatch[1]

	// Extract tbody if present
	tbodyPattern := regexp.MustCompile(`(?s)<tbody[^>]*>(.*?)</tbody>`)
	tbodyMatch := tbodyPattern.FindStringSubmatch(tableContent)
	var rowsContent string
	if len(tbodyMatch) >= 2 {
		rowsContent = tbodyMatch[1]
	} else {
		rowsContent = tableContent
	}

	// Extract all rows
	rowPattern := regexp.MustCompile(`(?s)<tr[^>]*>(.*?)</tr>`)
	rows := rowPattern.FindAllStringSubmatch(rowsContent, -1)

	for i, row := range rows {
		if len(row) < 2 {
			continue
		}
		tr := row[1]

		// Skip header row - detect by presence of <b> tags (typical in headers)
		if i == 0 && strings.Contains(tr, "<b>") {
			continue
		}

		// Extract all td elements
		tdPattern := regexp.MustCompile(`(?s)<td[^>]*>(.*?)</td>`)
		tds := tdPattern.FindAllStringSubmatch(tr, -1)

		if len(tds) < 2 {
			continue
		}

		// First td: file number (entity ID)
		fileNumber := strings.TrimSpace(tds[0][1])

		// Second td: entity name (may contain link)
		entityName := extractEntityNameFromTD(tds[1][1])

		// Third td (if present): status
		status := ""
		if len(tds) >= 3 {
			status = extractStatus(tds[2][1])
		}

		// Try to extract entity ID from hidden input or link in the row
		entityID := extractEntityIDFromRow(tr)
		if entityID == "" {
			entityID = fileNumber
		}

		if entityName != "" {
			entities = append(entities, Entity{
				ID:     entityID,
				Name:   entityName,
				Type:   "", // Delaware format doesn't have type in this view
				Status: status,
			})
		}
	}

	return entities
}

// extractEntityNameFromTD extracts entity name from a table cell that may contain a link
func extractEntityNameFromTD(tdContent string) string {
	// Try to find an <a> tag first
	linkPattern := regexp.MustCompile(`<a[^>]*>([^<]+)</a>`)
	linkMatch := linkPattern.FindStringSubmatch(tdContent)
	if len(linkMatch) > 1 {
		return strings.TrimSpace(linkMatch[1])
	}
	// Otherwise, just return the text content
	cleanPattern := regexp.MustCompile(`<[^>]+>`)
	cleaned := cleanPattern.ReplaceAllString(tdContent, "")
	return strings.TrimSpace(cleaned)
}

// extractStatus extracts status from a table cell
func extractStatus(tdContent string) string {
	// Try to find a span with status class
	statusPattern := regexp.MustCompile(`<span[^>]*class="[^"]*status[^"]*"[^>]*>([^<]+)</span>`)
	statusMatch := statusPattern.FindStringSubmatch(tdContent)
	if len(statusMatch) > 1 {
		return strings.TrimSpace(statusMatch[1])
	}
	// Otherwise, try to find any span content
	spanPattern := regexp.MustCompile(`<span[^>]*>([^<]+)</span>`)
	spanMatch := spanPattern.FindStringSubmatch(tdContent)
	if len(spanMatch) > 1 {
		return strings.TrimSpace(spanMatch[1])
	}
	// Clean HTML and return text
	cleanPattern := regexp.MustCompile(`<[^>]+>`)
	cleaned := cleanPattern.ReplaceAllString(tdContent, "")
	return strings.TrimSpace(cleaned)
}

// extractEntityIDFromRow extracts entity ID from hidden input or link URL
func extractEntityIDFromRow(tr string) string {
	// Try hidden input with name containing entityID
	hiddenPattern := regexp.MustCompile(`<input[^>]*name="[^"]*entityID[^"]*"[^>]*value="([^"]+)"`)
	hiddenMatch := hiddenPattern.FindStringSubmatch(tr)
	if len(hiddenMatch) > 1 {
		return strings.TrimSpace(hiddenMatch[1])
	}

	// Try hidden input with id containing entityID
	hiddenIdPattern := regexp.MustCompile(`<input[^>]*id="[^"]*entityID[^"]*"[^>]*value="([^"]+)"`)
	hiddenIdMatch := hiddenIdPattern.FindStringSubmatch(tr)
	if len(hiddenIdMatch) > 1 {
		return strings.TrimSpace(hiddenIdMatch[1])
	}

	// Try to find entityID in any URL
	urlPattern := regexp.MustCompile(`entityID=([^"&]+)`)
	urlMatch := urlPattern.FindStringSubmatch(tr)
	if len(urlMatch) > 1 {
		return strings.TrimSpace(urlMatch[1])
	}

	return ""
}
