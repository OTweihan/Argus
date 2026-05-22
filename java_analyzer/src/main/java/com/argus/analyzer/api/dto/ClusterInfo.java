package com.argus.analyzer.api.dto;

import java.util.List;

public class ClusterInfo {

    private String clusterId;
    private String suggestedLabel;
    private List<String> memberKeys;
    private int memberCount;

    public ClusterInfo() {}

    public ClusterInfo(String clusterId, String suggestedLabel, List<String> memberKeys) {
        this.clusterId = clusterId;
        this.suggestedLabel = suggestedLabel;
        this.memberKeys = memberKeys;
        this.memberCount = memberKeys != null ? memberKeys.size() : 0;
    }

    public String getClusterId() { return clusterId; }
    public void setClusterId(String clusterId) { this.clusterId = clusterId; }

    public String getSuggestedLabel() { return suggestedLabel; }
    public void setSuggestedLabel(String suggestedLabel) { this.suggestedLabel = suggestedLabel; }

    public List<String> getMemberKeys() { return memberKeys; }
    public void setMemberKeys(List<String> memberKeys) {
        this.memberKeys = memberKeys;
        this.memberCount = memberKeys != null ? memberKeys.size() : 0;
    }

    public int getMemberCount() { return memberCount; }
    public void setMemberCount(int memberCount) { this.memberCount = memberCount; }
}
