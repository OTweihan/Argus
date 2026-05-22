package com.argus.analyzer.api.dto;

import java.util.List;

public class EndpointInfo {

    private String path;
    private String httpMethod;
    private String controllerClass;
    private String controllerMethod;
    private List<String> parameters;
    private String returnType;

    public EndpointInfo() {}

    public EndpointInfo(String path, String httpMethod, String controllerClass,
                        String controllerMethod, List<String> parameters, String returnType) {
        this.path = path;
        this.httpMethod = httpMethod;
        this.controllerClass = controllerClass;
        this.controllerMethod = controllerMethod;
        this.parameters = parameters;
        this.returnType = returnType;
    }

    public String getPath() { return path; }
    public void setPath(String path) { this.path = path; }

    public String getHttpMethod() { return httpMethod; }
    public void setHttpMethod(String httpMethod) { this.httpMethod = httpMethod; }

    public String getControllerClass() { return controllerClass; }
    public void setControllerClass(String controllerClass) { this.controllerClass = controllerClass; }

    public String getControllerMethod() { return controllerMethod; }
    public void setControllerMethod(String controllerMethod) { this.controllerMethod = controllerMethod; }

    public List<String> getParameters() { return parameters; }
    public void setParameters(List<String> parameters) { this.parameters = parameters; }

    public String getReturnType() { return returnType; }
    public void setReturnType(String returnType) { this.returnType = returnType; }
}
