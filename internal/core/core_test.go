package core

import (
	"os"
	"path/filepath"
	"testing"
)

func TestParseEntitySearchResults_StandardFormat(t *testing.T) {
	// Read the test fixture
	html, err := os.ReadFile(filepath.Join("testdata", "entity_search_results.html"))
	if err != nil {
		t.Fatalf("Failed to read test fixture: %v", err)
	}

	entities, err := ParseEntitySearchResults(string(html))
	if err != nil {
		t.Fatalf("ParseEntitySearchResults returned error: %v", err)
	}

	if len(entities) != 3 {
		t.Errorf("Expected 3 entities, got %d", len(entities))
	}

	// Verify first entity
	if entities[0].Name != "ACME Corporation" {
		t.Errorf("Expected first entity name 'ACME Corporation', got '%s'", entities[0].Name)
	}
	if entities[0].ID != "12345" {
		t.Errorf("Expected first entity ID '12345', got '%s'", entities[0].ID)
	}
	if entities[0].Type != "Corporation" {
		t.Errorf("Expected first entity type 'Corporation', got '%s'", entities[0].Type)
	}
	if entities[0].Status != "active" {
		t.Errorf("Expected first entity status 'active', got '%s'", entities[0].Status)
	}

	// Verify second entity
	if entities[1].Name != "Beta LLC" {
		t.Errorf("Expected second entity name 'Beta LLC', got '%s'", entities[1].Name)
	}
	if entities[1].ID != "67890" {
		t.Errorf("Expected second entity ID '67890', got '%s'", entities[1].ID)
	}
	if entities[1].Type != "Limited Liability Company" {
		t.Errorf("Expected second entity type 'Limited Liability Company', got '%s'", entities[1].Type)
	}
	if entities[1].Status != "active" {
		t.Errorf("Expected second entity status 'active', got '%s'", entities[1].Status)
	}

	// Verify third entity
	if entities[2].Name != "Gamma Inc" {
		t.Errorf("Expected third entity name 'Gamma Inc', got '%s'", entities[2].Name)
	}
	if entities[2].Status != "inactive" {
		t.Errorf("Expected third entity status 'inactive', got '%s'", entities[2].Status)
	}
}

func TestParseEntitySearchResults_DelawareFormat(t *testing.T) {
	// Delaware ASP.NET format HTML
	html := `<!DOCTYPE html>
<html>
<head>
    <title>Delaware Entity Search</title>
</head>
<body>
    <form method="post">
        <table id="tblResults">
            <tbody>
                <tr>
                    <td bgcolor="#d7d7d7" width="113"><b>FILE NUMBER </b></td>
                    <td bgcolor="#d7d7d7" width="430"><b>ENTITY NAME</b></td>
                    <td bgcolor="#d7d7d7" width="200"><b>STATUS</b></td>
                </tr>
                <tr>
                    <td>1234567</td>
                    <td><a href="/entitydetail.aspx?entityID=1234567">Delaware Corp One</a></td>
                    <td><span class="status-active">Active</span></td>
                </tr>
                <tr>
                    <td>7654321</td>
                    <td><a href="/entitydetail.aspx?entityID=7654321">Second Delaware LLC</a></td>
                    <td><span class="status-active">Active</span></td>
                </tr>
            </tbody>
        </table>
    </form>
</body>
</html>`

	entities, err := ParseEntitySearchResults(html)
	if err != nil {
		t.Fatalf("ParseEntitySearchResults returned error: %v", err)
	}

	if len(entities) != 2 {
		t.Errorf("Expected 2 entities, got %d", len(entities))
	}

	// Verify first entity
	if entities[0].Name != "Delaware Corp One" {
		t.Errorf("Expected first entity name 'Delaware Corp One', got '%s'", entities[0].Name)
	}
	if entities[0].ID != "1234567" {
		t.Errorf("Expected first entity ID '1234567', got '%s'", entities[0].ID)
	}
	if entities[0].Status != "Active" {
		t.Errorf("Expected first entity status 'Active', got '%s'", entities[0].Status)
	}

	// Verify second entity
	if entities[1].Name != "Second Delaware LLC" {
		t.Errorf("Expected second entity name 'Second Delaware LLC', got '%s'", entities[1].Name)
	}
	if entities[1].ID != "7654321" {
		t.Errorf("Expected second entity ID '7654321', got '%s'", entities[1].ID)
	}
}

func TestParseEntitySearchResults_SimpleFormat(t *testing.T) {
	// Simple format without classes (fallback)
	html := `<!DOCTYPE html>
<html>
<body>
    <table>
        <tr>
            <td><a href="/entity/abc123">Simple Corp</a></td>
            <td>Corporation</td>
            <td>Active</td>
        </tr>
        <tr>
            <td><a href="/entity/def456">Another Entity</a></td>
            <td>LLC</td>
            <td>Active</td>
        </tr>
    </table>
</body>
</html>`

	entities, err := ParseEntitySearchResults(html)
	if err != nil {
		t.Fatalf("ParseEntitySearchResults returned error: %v", err)
	}

	if len(entities) != 2 {
		t.Errorf("Expected 2 entities, got %d", len(entities))
	}

	if entities[0].Name != "Simple Corp" {
		t.Errorf("Expected first entity name 'Simple Corp', got '%s'", entities[0].Name)
	}
	if entities[1].Name != "Another Entity" {
		t.Errorf("Expected second entity name 'Another Entity', got '%s'", entities[1].Name)
	}
}

func TestParseEntitySearchResults_EmptyHTML(t *testing.T) {
	html := `<!DOCTYPE html><html><body></body></html>`

	entities, err := ParseEntitySearchResults(html)
	if err != nil {
		t.Fatalf("ParseEntitySearchResults returned error: %v", err)
	}

	if len(entities) != 0 {
		t.Errorf("Expected 0 entities for empty HTML, got %d", len(entities))
	}
}

func TestParseEntitySearchResults_DelawareWithHiddenInput(t *testing.T) {
	// Delaware format with hidden input for entity ID
	html := `<!DOCTYPE html>
<html>
<body>
    <table id="tblResults">
        <tbody>
            <tr>
                <td><input type="hidden" name="entityID" value="999888777" /></td>
                <td>Hidden ID Corp</td>
                <td><span class="status-active">Active</span></td>
            </tr>
        </tbody>
    </table>
</body>
</html>`

	entities, err := ParseEntitySearchResults(html)
	if err != nil {
		t.Fatalf("ParseEntitySearchResults returned error: %v", err)
	}

	if len(entities) != 1 {
		t.Errorf("Expected 1 entity, got %d", len(entities))
	}

	if entities[0].ID != "999888777" {
		t.Errorf("Expected entity ID '999888777', got '%s'", entities[0].ID)
	}
	if entities[0].Name != "Hidden ID Corp" {
		t.Errorf("Expected entity name 'Hidden ID Corp', got '%s'", entities[0].Name)
	}
}
