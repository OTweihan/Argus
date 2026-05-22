package com.argus.analyzer.api.dto;

public class FindingItem {

    private String ruleId;
    private String severity;
    private String title;
    private String description;
    private String filePath;
    private int lineNumber;
    private String snippet;

    public FindingItem() {}

    public FindingItem(String ruleId, String severity, String title, String description,
                       String filePath, int lineNumber, String snippet) {
        this.ruleId = ruleId;
        this.severity = severity;
        this.title = title;
        this.description = description;
        this.filePath = filePath;
        this.lineNumber = lineNumber;
        this.snippet = snippet;
    }

    public String getRuleId() { return ruleId; }
    public void setRuleId(String ruleId) { this.ruleId = ruleId; }

    public String getSeverity() { return severity; }
    public void setSeverity(String severity) { this.severity = severity; }

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }

    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }

    public String getFilePath() { return filePath; }
    public void setFilePath(String filePath) { this.filePath = filePath; }

    public int getLineNumber() { return lineNumber; }
    public void setLineNumber(int lineNumber) { this.lineNumber = lineNumber; }

    public String getSnippet() { return snippet; }
    public void setSnippet(String snippet) { this.snippet = snippet; }
}
