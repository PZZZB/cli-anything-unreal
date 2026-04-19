def format_material_connections_mermaid(result: dict) -> str:
    """Format material connections as a Mermaid flowchart diagram.
    
    Args:
        result: Dictionary returned by get_material_connections()
        
    Returns:
        Mermaid formatted string.
    """
    if "error" in result:
        return f"Error: {result['error']}"

    material_name = result.get("material", "").split("/")[-1]
    mat_outputs = result.get("material_outputs", {})
    edges = result.get("edges", [])
    nodes = {n["name"]: n for n in result.get("nodes", [])}
    orphan_names = set(result.get("orphan_nodes", []))

    lines = [
        "```mermaid",
        f"%% Material Graph: {material_name}",
        "graph TD",
    ]

    # Style definitions
    lines.append("    classDef outputPin fill:#2a2a2a,stroke:#3b82f6,stroke-width:2px,color:#fff;")
    lines.append("    classDef customNode fill:#4d1d1d,stroke:#ef4444,stroke-width:2px,color:#fff;")
    lines.append("    classDef textureNode fill:#1e3a8a,stroke:#60a5fa,stroke-width:2px,color:#fff;")
    lines.append("    classDef paramNode fill:#14532d,stroke:#4ade80,stroke-width:2px,color:#fff;")
    lines.append("    classDef mathNode fill:#3f3f46,stroke:#a1a1aa,stroke-width:1px,color:#fff;")
    lines.append("    classDef orphanNode fill:#1f2937,stroke:#dc2626,stroke-width:1px,stroke-dasharray: 5 5,color:#9ca3af;")
    lines.append("")

    def _get_node_label(name: str) -> str:
        node_info = nodes.get(name, {})
        n_type = node_info.get("type", "").replace("MaterialExpression", "")
        # Add param names or specific details if available
        desc = node_info.get("desc", "")
        if desc:
            return f"{name}<br/><i>{n_type}</i><br/><b>'{desc}'</b>"
        return f"{name}<br/><i>{n_type}</i>"

    def _get_node_class(name: str) -> str:
        if name in orphan_names:
            return "orphanNode"
        node_info = nodes.get(name, {})
        n_type = node_info.get("type", "")
        if "Custom" in n_type:
            return "customNode"
        if "Texture" in n_type:
            return "textureNode"
        if "Parameter" in n_type or "Constant" in n_type:
            return "paramNode"
        return "mathNode"

    # Material Output Node (the main result node)
    out_node_id = "MAT_OUTPUT"
    lines.append(f"    {out_node_id}[\"{material_name} (Material)\"]:::outputPin")

    # Keep track of nodes we've added to the diagram
    rendered_nodes = set()

    # Draw connections to Material Output
    for pin_name, src in mat_outputs.items():
        if isinstance(src, dict) and "node" in src:
            src_node = src["node"]
            out_pin = src.get("output", "")
            edge_label = f"|{out_pin}|" if out_pin else ""
            lines.append(f"    {src_node} --{edge_label}-->|{pin_name}| {out_node_id}")
            rendered_nodes.add(src_node)

    # Draw internal edges
    for edge in edges:
        from_node = edge["from_node"]
        to_node = edge["to_node"]
        input_idx = edge.get("to_input_index", "")
        
        edge_label = f"|in:{input_idx}|" if input_idx != "" else ""
        lines.append(f"    {from_node} --{edge_label}--> {to_node}")
        rendered_nodes.add(from_node)
        rendered_nodes.add(to_node)

    # Define nodes with labels and styles
    lines.append("")
    for name in rendered_nodes:
        label = _get_node_label(name)
        cls = _get_node_class(name)
        lines.append(f"    {name}[\"{label}\"]:::{cls}")

    lines.append("```")
    return "\n".join(lines)
