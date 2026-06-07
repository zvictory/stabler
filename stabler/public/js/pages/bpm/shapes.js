/**
 * BPMN 2.0 shape catalog — single source of truth for palette, renderers, and inspector.
 *
 * category ∈ "event" | "activity" | "gateway" | "data" | "annotation"
 *   → maps to one vue-flow node type (EventNode, ActivityNode, …)
 *
 * For events:
 *   ring     ∈ "start" | "intermediate" | "throw" | "end"
 *   trigger  ∈ "none" | "message" | "timer" | "conditional" | "signal" |
 *              "error" | "escalation" | "link" | "terminate" | "compensation"
 *
 * For activities:
 *   marker ∈ null | "plus" (subprocess) | "thick" (call-activity border)
 *
 * For gateways:
 *   glyph ∈ "X" | "+" | "O" | "E" | "*"
 *
 * For data:
 *   shape ∈ "page" | "page-in" | "page-out" | "cylinder" | "document" | "collection"
 *
 * For annotation:
 *   shape ∈ "bracket" | "group"
 */
export const SHAPE_CATALOG = [
	// ── Events ──────────────────────────────────────────────────────────────
	// Start (thin single ring, green by default)
	{ key: "event-start-none",         category: "event", ring: "start",        trigger: "none",         label: "Start",               icon: "ti-circle",            defaultColor: "#2fb344", defaultW: 44, defaultH: 44 },
	{ key: "event-start-message",      category: "event", ring: "start",        trigger: "message",      label: "Message Start",       icon: "ti-mail",              defaultColor: "#2fb344", defaultW: 44, defaultH: 44 },
	{ key: "event-start-timer",        category: "event", ring: "start",        trigger: "timer",        label: "Timer Start",         icon: "ti-clock",             defaultColor: "#2fb344", defaultW: 44, defaultH: 44 },
	{ key: "event-start-conditional",  category: "event", ring: "start",        trigger: "conditional",  label: "Conditional Start",   icon: "ti-list",              defaultColor: "#2fb344", defaultW: 44, defaultH: 44 },
	{ key: "event-start-signal",       category: "event", ring: "start",        trigger: "signal",       label: "Signal Start",        icon: "ti-alert-triangle",    defaultColor: "#2fb344", defaultW: 44, defaultH: 44 },

	// Intermediate catch (double thin ring, blue)
	{ key: "event-catch-none",         category: "event", ring: "intermediate", trigger: "none",         label: "Intermediate",        icon: "ti-circle",            defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-catch-message",      category: "event", ring: "intermediate", trigger: "message",      label: "Message Catch",       icon: "ti-mail",              defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-catch-timer",        category: "event", ring: "intermediate", trigger: "timer",        label: "Timer",               icon: "ti-clock",             defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-catch-error",        category: "event", ring: "intermediate", trigger: "error",        label: "Error Catch",         icon: "ti-bolt",              defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-catch-signal",       category: "event", ring: "intermediate", trigger: "signal",       label: "Signal Catch",        icon: "ti-alert-triangle",    defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-catch-escalation",   category: "event", ring: "intermediate", trigger: "escalation",   label: "Escalation Catch",    icon: "ti-arrow-up",          defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-catch-link",         category: "event", ring: "intermediate", trigger: "link",         label: "Link Catch",          icon: "ti-arrow-right",       defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },

	// Intermediate throw (double ring, filled glyph, blue)
	{ key: "event-throw-message",      category: "event", ring: "throw",        trigger: "message",      label: "Message Throw",       icon: "ti-mail-forward",      defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-throw-signal",       category: "event", ring: "throw",        trigger: "signal",       label: "Signal Throw",        icon: "ti-alert-triangle",    defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-throw-escalation",   category: "event", ring: "throw",        trigger: "escalation",   label: "Escalation Throw",    icon: "ti-arrow-up",          defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-throw-link",         category: "event", ring: "throw",        trigger: "link",         label: "Link Throw",          icon: "ti-arrow-right",       defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },
	{ key: "event-throw-compensation", category: "event", ring: "throw",        trigger: "compensation", label: "Compensation",        icon: "ti-repeat",            defaultColor: "#4299e1", defaultW: 44, defaultH: 44 },

	// End (thick single ring, red)
	{ key: "event-end-none",           category: "event", ring: "end",          trigger: "none",         label: "End",                 icon: "ti-circle-filled",     defaultColor: "#f03e3e", defaultW: 44, defaultH: 44 },
	{ key: "event-end-message",        category: "event", ring: "end",          trigger: "message",      label: "Message End",         icon: "ti-mail",              defaultColor: "#f03e3e", defaultW: 44, defaultH: 44 },
	{ key: "event-end-error",          category: "event", ring: "end",          trigger: "error",        label: "Error End",           icon: "ti-bolt",              defaultColor: "#f03e3e", defaultW: 44, defaultH: 44 },
	{ key: "event-end-signal",         category: "event", ring: "end",          trigger: "signal",       label: "Signal End",          icon: "ti-alert-triangle",    defaultColor: "#f03e3e", defaultW: 44, defaultH: 44 },
	{ key: "event-end-terminate",      category: "event", ring: "end",          trigger: "terminate",    label: "Terminate",           icon: "ti-player-stop",       defaultColor: "#f03e3e", defaultW: 44, defaultH: 44 },
	{ key: "event-end-escalation",     category: "event", ring: "end",          trigger: "escalation",   label: "Escalation End",      icon: "ti-arrow-up",          defaultColor: "#f03e3e", defaultW: 44, defaultH: 44 },
	{ key: "event-end-compensation",   category: "event", ring: "end",          trigger: "compensation", label: "Compensation End",    icon: "ti-repeat",            defaultColor: "#f03e3e", defaultW: 44, defaultH: 44 },

	// ── Activities ───────────────────────────────────────────────────────────
	{ key: "task",                     category: "activity", marker: null,    label: "Task",           icon: "ti-square",           defaultColor: "#4299e1", defaultW: 120, defaultH: 60 },
	{ key: "task-user",                category: "activity", marker: null,    label: "User Task",      icon: "ti-user",             defaultColor: "#4299e1", defaultW: 120, defaultH: 60 },
	{ key: "task-service",             category: "activity", marker: null,    label: "Service Task",   icon: "ti-settings",         defaultColor: "#4299e1", defaultW: 120, defaultH: 60 },
	{ key: "task-send",                category: "activity", marker: null,    label: "Send Task",      icon: "ti-send",             defaultColor: "#4299e1", defaultW: 120, defaultH: 60 },
	{ key: "task-receive",             category: "activity", marker: null,    label: "Receive Task",   icon: "ti-inbox",            defaultColor: "#4299e1", defaultW: 120, defaultH: 60 },
	{ key: "task-manual",              category: "activity", marker: null,    label: "Manual Task",    icon: "ti-hand-stop",        defaultColor: "#4299e1", defaultW: 120, defaultH: 60 },
	{ key: "task-script",              category: "activity", marker: null,    label: "Script Task",    icon: "ti-code",             defaultColor: "#4299e1", defaultW: 120, defaultH: 60 },
	{ key: "task-businessrule",        category: "activity", marker: null,    label: "Business Rule",  icon: "ti-license",          defaultColor: "#4299e1", defaultW: 120, defaultH: 60 },
	{ key: "subprocess",               category: "activity", marker: "plus",  label: "Sub-Process",    icon: "ti-layout-grid",      defaultColor: "#4299e1", defaultW: 140, defaultH: 70 },
	{ key: "call-activity",            category: "activity", marker: "thick", label: "Call Activity",  icon: "ti-phone",            defaultColor: "#4299e1", defaultW: 120, defaultH: 60 },

	// ── Gateways ─────────────────────────────────────────────────────────────
	{ key: "gateway-exclusive",        category: "gateway", glyph: "X", label: "Exclusive (XOR)", icon: "ti-shape",      defaultColor: "#f59f00", defaultW: 60, defaultH: 60 },
	{ key: "gateway-parallel",         category: "gateway", glyph: "+", label: "Parallel (AND)",  icon: "ti-plus",       defaultColor: "#f59f00", defaultW: 60, defaultH: 60 },
	{ key: "gateway-inclusive",        category: "gateway", glyph: "O", label: "Inclusive (OR)",  icon: "ti-circle",     defaultColor: "#f59f00", defaultW: 60, defaultH: 60 },
	{ key: "gateway-event",            category: "gateway", glyph: "E", label: "Event-Based",     icon: "ti-star",       defaultColor: "#f59f00", defaultW: 60, defaultH: 60 },
	{ key: "gateway-complex",          category: "gateway", glyph: "*", label: "Complex",         icon: "ti-asterisk",   defaultColor: "#f59f00", defaultW: 60, defaultH: 60 },

	// ── Data ─────────────────────────────────────────────────────────────────
	{ key: "data-object",              category: "data", shape: "page",       label: "Data Object",  icon: "ti-file",              defaultColor: "#868e96", defaultW: 50, defaultH: 68 },
	{ key: "data-input",               category: "data", shape: "page-in",    label: "Data Input",   icon: "ti-file-import",       defaultColor: "#868e96", defaultW: 50, defaultH: 68 },
	{ key: "data-output",              category: "data", shape: "page-out",   label: "Data Output",  icon: "ti-file-export",       defaultColor: "#868e96", defaultW: 50, defaultH: 68 },
	{ key: "data-store",               category: "data", shape: "cylinder",   label: "Data Store",   icon: "ti-database",          defaultColor: "#868e96", defaultW: 70, defaultH: 58 },
	{ key: "document",                 category: "data", shape: "document",   label: "Document",     icon: "ti-file-description",  defaultColor: "#868e96", defaultW: 80, defaultH: 70 },
	{ key: "collection",               category: "data", shape: "collection", label: "Collection",   icon: "ti-files",             defaultColor: "#868e96", defaultW: 50, defaultH: 68 },

	// ── Annotations ──────────────────────────────────────────────────────────
	{ key: "annotation",               category: "annotation", shape: "bracket", label: "Annotation", icon: "ti-message-2",   defaultColor: "#495057", defaultW: 140, defaultH: 50 },
	{ key: "group",                    category: "annotation", shape: "group",   label: "Group",      icon: "ti-layout-2",    defaultColor: "#adb5bd", defaultW: 200, defaultH: 150 },
];

/**
 * Returns the catalog entry for a shape key, falling back to "task".
 */
export function shapeDef(key) {
	return SHAPE_CATALOG.find((s) => s.key === key) || SHAPE_CATALOG.find((s) => s.key === "task");
}

/**
 * Maps legacy node type+variant to a catalog key (back-compat for existing diagrams).
 * Called in normalizeDiagram() when a node has no data.shape.
 */
export function legacyToShape(type, variant) {
	if (type === "startend") return variant === "end" ? "event-end-none" : "event-start-none";
	if (type === "decision") return "gateway-exclusive";
	if (type === "task") return "task";
	// If already a new key (in case of partial migration), pass through.
	if (SHAPE_CATALOG.some((s) => s.key === type)) return type;
	return "task";
}

/**
 * Category display order and display metadata (for palette section headers).
 */
export const CATEGORY_META = {
	event:      { label: "Events",      icon: "ti-circle"   },
	activity:   { label: "Activities",  icon: "ti-square"   },
	gateway:    { label: "Gateways",    icon: "ti-shape"    },
	data:       { label: "Data",        icon: "ti-database" },
	annotation: { label: "Artifacts",   icon: "ti-message-2" },
};

export const CATEGORY_ORDER = ["event", "activity", "gateway", "data", "annotation"];

/**
 * Returns a Map<category, shape[]> preserving display order.
 */
export function shapesByCategory() {
	const map = new Map(CATEGORY_ORDER.map((k) => [k, []]));
	for (const s of SHAPE_CATALOG) {
		if (map.has(s.category)) map.get(s.category).push(s);
	}
	return map;
}
