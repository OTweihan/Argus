import {request} from "../client";
import type {ConfigSummary} from "../../types";

export function summary(): Promise<ConfigSummary> {
    return request<ConfigSummary>("/config/summary");
}
