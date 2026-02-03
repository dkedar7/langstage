"""UI components for rendering messages, canvas items, and other UI elements."""

import json
from datetime import datetime
from typing import Dict, List, Optional
from dash import html, dcc
import dash_mantine_components as dmc
from dash_iconify import DashIconify


def format_message(role: str, content: str, colors: Dict, styles: Dict, is_new: bool = False, response_time: float = None):
    """Format a chat message.

    Args:
        role: 'user' or 'assistant'
        content: Message content
        colors: Color scheme dict
        styles: Styles dict
        is_new: Whether this is a new message (for animation)
        response_time: Time in seconds it took to generate the response (agent messages only)
    """
    is_user = role == "user"

    # Render content as markdown for assistant messages, plain text for user
    if is_user:
        content_element = html.Div(content, style={
            "fontSize": "15px", "lineHeight": "1.5", "whiteSpace": "pre-wrap",
        })
    else:
        content_element = dcc.Markdown(
            content,
            style={
                "fontSize": "15px",
                "lineHeight": "1.5",
            }
        )

    # Use CSS classes for theme-aware styling
    message_class = "message-enter chat-message" if is_new else "chat-message"
    if is_user:
        message_class += " chat-message-user"
    else:
        message_class += " chat-message-agent"

    # Build header with role and optional response time
    header_children = [
        html.Span("You" if is_user else "Agent", className="message-role-user" if is_user else "message-role-agent", style={
            "fontSize": "12px", "fontWeight": "500",
            "textTransform": "uppercase", "letterSpacing": "0.4px",
        })
    ]

    # Add response time for agent messages
    if not is_user and response_time is not None:
        if response_time >= 60:
            minutes = int(response_time // 60)
            seconds = int(response_time % 60)
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{int(response_time)}s"
        header_children.append(
            html.Span(time_str, className="message-time", style={
                "fontSize": "12px", "marginLeft": "8px",
            })
        )

    return html.Div([
        html.Div(header_children, style={"marginBottom": "5px"}),
        content_element
    ], className=message_class, style={
        "padding": "12px 15px",
    })


def format_loading(colors: Dict):
    """Format loading indicator with dots loader."""
    return html.Div([
        dmc.Loader(type="dots", size="sm")
    ], className="chat-message chat-message-loading", style={
        "padding": "12px 15px",
    })


def format_thinking(thinking_text: str, colors: Dict):
    """Format thinking as an inline subordinate message."""
    if not thinking_text:
        return None

    return html.Details([
        html.Summary("Thinking", className="details-summary details-summary-thinking"),
        html.Div(thinking_text, className="details-content details-content-thinking", style={
            "whiteSpace": "pre-wrap",
        })
    ], open=True, className="chat-details", style={
        "marginBottom": "4px",
    })


def format_todos(todos, colors: Dict):
    """Format todo list. Handles both list format [{"content": ..., "status": ...}] and dict format {task_name: status}."""
    if not todos:
        return html.Span("No tasks", style={"color": colors["text_muted"], "fontStyle": "italic", "fontSize": "14px"})

    items = []

    # Normalize to list of (task_name, status) tuples
    todo_list = []
    if isinstance(todos, list):
        # List format: [{"content": "task", "status": "pending"}, ...]
        for item in todos:
            if isinstance(item, dict):
                task_name = item.get("content", "")
                status = item.get("status", "pending")
                todo_list.append((task_name, status))
    elif isinstance(todos, dict):
        # Dict format: {task_name: status}
        for task_name, status in todos.items():
            todo_list.append((task_name, status))

    for task_name, status in todo_list:
        # Determine checkbox symbol and styling based on status
        if status == "completed":
            checkbox_symbol = "✓"
            checkbox_color = colors["todo"]
            text_color = colors["text_muted"]
            text_decoration = "line-through"
            font_weight = "bold"
        elif status == "in_progress":
            checkbox_symbol = "◐"
            checkbox_color = colors["warning"]
            text_color = colors["text_primary"]
            text_decoration = "none"
            font_weight = "bold"
        else:  # pending
            checkbox_symbol = "○"
            checkbox_color = colors["text_muted"]
            text_color = colors["text_primary"]
            text_decoration = "none"
            font_weight = "normal"

        checkbox = html.Span(
            checkbox_symbol,
            style={
                "fontSize": "14px",
                "color": checkbox_color,
                "marginRight": "8px",
                "fontWeight": font_weight,
            }
        )

        items.append(html.Div([
            checkbox,
            html.Span(task_name, style={
                "fontSize": "14px",
                "color": text_color,
                "textDecoration": text_decoration,
                "fontWeight": font_weight if status == "in_progress" else "normal",
            })
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px"}))

    return html.Div(items)


def format_todos_inline(todos, colors: Dict):
    """Format todos as an inline subordinate message."""
    if not todos:
        return None

    todo_items = format_todos(todos, colors)

    return html.Details([
        html.Summary("Tasks", className="details-summary details-summary-todo"),
        html.Div(todo_items, className="details-content details-content-todo")
    ], open=True, className="chat-details", style={
        "marginBottom": "4px",
    })


def format_tool_call(tool_call: Dict, colors: Dict, is_completed: bool = False):
    """Format a single tool call as a collapsible submessage.

    Args:
        tool_call: Dict with 'name', 'args', and optionally 'result', 'status'
        colors: Color scheme dict
        is_completed: Whether the tool call has completed
    """
    tool_name = tool_call.get("name", "unknown")
    tool_args = tool_call.get("args", {})
    tool_result = tool_call.get("result")
    tool_status = tool_call.get("status", "pending")

    # Status class for styling
    if tool_status == "success":
        status_class = "tool-call-success"
    elif tool_status == "error":
        status_class = "tool-call-error"
    elif tool_status == "running":
        status_class = "tool-call-running"
    else:  # pending
        status_class = "tool-call-pending"

    # Format args for display (truncate if too long)
    args_display = ""
    if tool_args:
        try:
            args_str = json.dumps(tool_args, indent=2)
            if len(args_str) > 500:
                args_str = args_str[:500] + "..."
            args_display = args_str
        except:
            args_display = str(tool_args)[:500]

    # Build inner content (shown when expanded)
    inner_children = []

    # Arguments section
    if args_display:
        inner_children.append(html.Details([
            html.Summary("Arguments", className="tool-call-summary"),
            html.Pre(args_display, className="tool-call-args")
        ]))

    # Result section (only if completed)
    if tool_result is not None and is_completed:
        # Special handling for display_inline results - render them richly
        if tool_name == "display_inline" and isinstance(tool_result, dict) and tool_result.get("type") == "display_inline":
            inner_children.append(render_display_inline_result(tool_result, colors))
        else:
            result_display = str(tool_result)
            if len(result_display) > 500:
                result_display = result_display[:500] + "..."

            inner_children.append(html.Details([
                html.Summary("Result", className="tool-call-summary"),
                html.Pre(result_display, className="tool-call-result")
            ]))

    # Wrap entire tool call in a details element
    return html.Details([
        html.Summary([
            html.Span(className="tool-call-status-dot"),
            html.Span(tool_name, className="tool-call-name"),
        ], className="tool-call-header"),
        html.Div(inner_children, className="tool-call-body") if inner_children else None
    ], className=f"tool-call {status_class}")


def render_display_inline_result(result: Dict, colors: Dict) -> html.Div:
    """Render display_inline tool result as rich interactive content.

    Args:
        result: The display_inline result dictionary
        colors: Color scheme dict

    Returns:
        A Dash html.Div component with the rendered content
    """
    display_type = result.get("display_type", "text")
    title = result.get("title")
    data = result.get("data")
    preview = result.get("preview")
    error = result.get("error")
    status = result.get("status", "success")
    filename = result.get("filename")
    downloadable = result.get("downloadable", False)
    csv_data = result.get("csv")

    # Get item ID for potential debugging
    item_id = result.get("_item_id", "unknown")

    # Build title header if present
    header_children = []
    if title:
        header_children.append(
            html.Div(title, className="display-inline-title", style={
                "fontWeight": "600",
                "fontSize": "15px",
                "marginBottom": "8px",
            })
        )

    # Error state
    if status == "error":
        return html.Div([
            *header_children,
            html.Div([
                html.Span("Error: ", style={"fontWeight": "600"}),
                html.Span(error or "Unknown error")
            ], className="display-inline-error", style={
                "color": "#e53e3e",
                "padding": "10px",
                "borderRadius": "5px",
                "backgroundColor": "rgba(229, 62, 62, 0.1)",
            })
        ], className="display-inline-container")

    content_element = None

    # Render based on display type
    if display_type == "image":
        mime_type = result.get("mime_type", "image/png")
        data_url = f"data:{mime_type};base64,{data}"
        content_element = html.Img(
            src=data_url,
            className="display-inline-image",
            style={
                "maxWidth": "100%",
                "maxHeight": "400px",
                "borderRadius": "5px",
                "objectFit": "contain",
            }
        )

    elif display_type == "plotly":
        content_element = dcc.Graph(
            figure=data,
            config={"displayModeBar": True, "responsive": True},
            style={"height": "350px"},
            className="display-inline-plotly"
        )

    elif display_type == "dataframe":
        # Show preview with expand option for full data
        preview_html = preview.get("html", "") if isinstance(preview, dict) else ""
        rows_shown = preview.get("rows_shown", 0) if isinstance(preview, dict) else 0
        total_rows = preview.get("total_rows", 0) if isinstance(preview, dict) else 0
        columns = preview.get("columns", []) if isinstance(preview, dict) else []

        # Summary line
        summary = f"{total_rows} rows × {len(columns)} columns"
        if rows_shown < total_rows:
            summary += f" (showing first {rows_shown})"

        content_element = html.Div([
            html.Div(summary, className="display-inline-df-summary", style={
                "fontSize": "12px",
                "marginBottom": "5px",
                "opacity": "0.8",
            }),
            html.Div(
                dcc.Markdown(preview_html, dangerously_allow_html=True),
                className="display-inline-dataframe",
                style={
                    "overflowX": "auto",
                    "maxHeight": "300px",
                    "overflowY": "auto",
                }
            )
        ])

    elif display_type == "html":
        # Show HTML preview directly in iframe (like PDF)
        if not data:
            content_element = html.Div(
                "Error: HTML content is empty or missing",
                style={"color": "red", "padding": "10px"}
            )
        else:
            # Create fullscreen button
            fullscreen_btn = html.Button(
                DashIconify(icon="mdi:fullscreen", width=18),
                id={"type": "fullscreen-btn", "index": item_id},
                className="fullscreen-btn",
                title="View fullscreen",
                style={
                    "position": "absolute",
                    "top": "8px",
                    "right": "8px",
                    "background": "rgba(255,255,255,0.9)",
                    "border": "1px solid #ddd",
                    "borderRadius": "4px",
                    "cursor": "pointer",
                    "padding": "4px 6px",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "zIndex": "10",
                }
            )
            # Store data for fullscreen modal
            fullscreen_store = dcc.Store(
                id={"type": "fullscreen-data", "index": item_id},
                data={"type": "html", "content": data, "title": title or "HTML Preview"}
            )
            content_element = html.Div([
                fullscreen_btn,
                html.Iframe(
                    srcDoc=data,
                    style={
                        "width": "100%",
                        "height": "400px",
                        "border": "none",
                        "borderRadius": "5px",
                        "backgroundColor": "white",
                    }
                ),
                fullscreen_store,
            ], style={"position": "relative"})

    elif display_type == "pdf":
        mime_type = result.get("mime_type", "application/pdf")
        # Debug: Check if data exists
        if not data:
            content_element = html.Div(
                "Error: PDF data is empty or missing",
                style={"color": "red", "padding": "10px"}
            )
        else:
            data_url = f"data:{mime_type};base64,{data}"
            # Create fullscreen button
            fullscreen_btn = html.Button(
                DashIconify(icon="mdi:fullscreen", width=18),
                id={"type": "fullscreen-btn", "index": item_id},
                className="fullscreen-btn",
                title="View fullscreen",
                style={
                    "position": "absolute",
                    "top": "8px",
                    "right": "8px",
                    "background": "rgba(255,255,255,0.9)",
                    "border": "1px solid #ddd",
                    "borderRadius": "4px",
                    "cursor": "pointer",
                    "padding": "4px 6px",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "zIndex": "10",
                }
            )
            # Store data for fullscreen modal
            fullscreen_store = dcc.Store(
                id={"type": "fullscreen-data", "index": item_id},
                data={"type": "pdf", "content": data_url, "title": title or "PDF Preview"}
            )
            # Use iframe instead of embed for better browser compatibility
            content_element = html.Div([
                fullscreen_btn,
                html.Iframe(
                    src=data_url,
                    style={
                        "width": "100%",
                        "height": "400px",
                        "border": "none",
                        "borderRadius": "5px",
                    }
                ),
                fullscreen_store,
            ], style={"position": "relative"})

    elif display_type == "json":
        json_str = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
        content_element = html.Details([
            html.Summary("JSON Data", className="tool-call-summary"),
            html.Pre(json_str, className="display-inline-json", style={
                "maxHeight": "300px",
                "overflowY": "auto",
                "fontSize": "12px",
                "padding": "10px",
                "borderRadius": "5px",
            })
        ])

    else:  # text or unknown
        text_content = str(data) if data else ""
        if len(text_content) > 1000:
            content_element = html.Details([
                html.Summary(f"Text ({len(text_content)} chars)", className="tool-call-summary"),
                html.Pre(text_content, className="display-inline-text", style={
                    "maxHeight": "300px",
                    "overflowY": "auto",
                    "whiteSpace": "pre-wrap",
                    "fontSize": "13px",
                })
            ])
        else:
            content_element = html.Pre(text_content, className="display-inline-text", style={
                "whiteSpace": "pre-wrap",
                "fontSize": "13px",
            })

    # Build footer with download option if applicable
    footer_children = []
    if filename:
        footer_children.append(
            html.Span(filename, className="display-inline-filename", style={
                "fontSize": "11px",
                "opacity": "0.7",
            })
        )

    # Assemble final component with collapsible wrapper
    # Note: Dash components evaluate to False in boolean context, so use 'is not None'

    # Build the summary label for the collapsible header
    display_type_labels = {
        "image": "📷 Image",
        "plotly": "📊 Chart",
        "dataframe": "📋 Table",
        "html": "🌐 HTML",
        "pdf": "📄 PDF",
        "json": "📝 JSON",
        "text": "📝 Text",
        "error": "⚠️ Error",
    }
    type_label = display_type_labels.get(display_type, "📎 Content")
    summary_text = f"{type_label}: {title}" if title else type_label
    if filename:
        summary_text += f" ({filename})"

    # Content to show inside the collapsible section
    content_children = []
    if content_element is not None:
        content_children.append(content_element)
    if footer_children:
        content_children.append(
            html.Div(footer_children, style={"marginTop": "5px"})
        )

    # Create "Add to Canvas" button with pattern-matching ID
    # Using html.Button for reliable n_clicks behavior (DMC Tooltip can interfere with callbacks)
    add_to_canvas_btn = html.Button(
        DashIconify(icon="mdi:palette-outline", width=16),
        id={"type": "add-display-to-canvas-btn", "index": item_id},
        className="add-to-canvas-btn",
        title="Add to Canvas",
        style={
            "background": "transparent",
            "border": "none",
            "cursor": "pointer",
            "padding": "4px",
            "borderRadius": "4px",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
        }
    )

    # Store the result data in a hidden div for the callback to retrieve
    result_store = dcc.Store(
        id={"type": "display-inline-data", "index": item_id},
        data=result
    )

    # Build summary with text and button
    summary_content = html.Div([
        html.Span(summary_text, className="display-inline-summary-text"),
        add_to_canvas_btn,
    ], className="display-inline-summary-row", style={
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
        "width": "100%",
    })

    return html.Details([
        html.Summary(summary_content, className="display-inline-summary"),
        html.Div(content_children, className="display-inline-content", style={
            "marginTop": "8px",
        }),
        result_store,  # Hidden store for callback data
    ], className="display-inline-container", open=True, style={
        "padding": "10px",
        "borderRadius": "8px",
        "marginTop": "5px",
    })


def extract_display_inline_results(tool_calls: List[Dict], colors: Dict) -> List:
    """Extract and render display_inline results prominently from tool calls.

    This function finds all display_inline tool results and renders them
    as standalone visual elements that appear alongside messages, rather
    than buried in the tool call details.

    Args:
        tool_calls: List of tool call dicts with 'name', 'args', 'result', 'status'
        colors: Color scheme dict

    Returns:
        List of rendered display_inline components (may be empty)
    """
    if not tool_calls:
        return []

    results = []
    for tc in tool_calls:
        if tc.get("name") == "display_inline" and tc.get("status") in ("success", "error"):
            result = tc.get("result")
            # Check if result is a dict with display_inline structure
            if isinstance(result, dict) and result.get("type") == "display_inline":
                rendered = render_display_inline_result(result, colors)
                results.append(rendered)

    return results


def extract_thinking_from_tool_calls(tool_calls: List[Dict], colors: Dict) -> List:
    """Extract think_tool calls and render them as thinking blocks.

    Args:
        tool_calls: List of tool call dicts with 'name', 'args', 'result', 'status'
        colors: Color scheme dict

    Returns:
        List of rendered thinking components (may be empty)
    """
    if not tool_calls:
        return []

    results = []
    for tc in tool_calls:
        if tc.get("name") == "think_tool" and tc.get("status") in ("success", "error"):
            result = tc.get("result")
            if result:
                # Extract thinking text from result
                thinking_text = ""
                if isinstance(result, str):
                    thinking_text = result
                elif isinstance(result, dict):
                    thinking_text = result.get("reflection", str(result))

                if thinking_text:
                    thinking_block = format_thinking(thinking_text, colors)
                    if thinking_block:
                        results.append(thinking_block)

    return results


def format_tool_calls_inline(tool_calls: List[Dict], colors: Dict):
    """Format multiple tool calls as an inline collapsible section.

    Args:
        tool_calls: List of tool call dicts with 'name', 'args', 'result', 'status'
        colors: Color scheme dict

    Note: think_tool calls are excluded from this rendering - they are rendered
    separately via extract_thinking_from_tool_calls() to appear in correct order.
    """
    if not tool_calls:
        return None

    # Filter out think_tool calls - they are rendered separately as thinking blocks
    filtered_tool_calls = [tc for tc in tool_calls if tc.get("name") != "think_tool"]

    if not filtered_tool_calls:
        return None

    # Count statuses (on filtered list)
    completed = sum(1 for tc in filtered_tool_calls if tc.get("status") in ("success", "error"))
    total = len(filtered_tool_calls)
    running = sum(1 for tc in filtered_tool_calls if tc.get("status") == "running")

    # Summary text and class
    if running > 0:
        summary_text = f"Tools ({completed}/{total}, {running} running)"
        summary_class = "details-summary details-summary-warning"
    elif completed == total:
        summary_text = f"Tools ({total} done)"
        summary_class = "details-summary details-summary-success"
    else:
        summary_text = f"Tools ({completed}/{total})"
        summary_class = "details-summary details-summary-muted"

    tool_elements = [
        format_tool_call(tc, colors, is_completed=tc.get("status") in ("success", "error"))
        for tc in filtered_tool_calls
    ]

    return html.Details([
        html.Summary(summary_text, className=summary_class),
        html.Div(tool_elements, style={
            "paddingLeft": "10px",
        })
    ], open=False, className="chat-details", style={
        "marginBottom": "5px",
    })


def format_interrupt(interrupt_data: Dict, colors: Dict):
    """Format an interrupt request for human-in-the-loop interaction.

    Args:
        interrupt_data: Dict with 'action_requests' and/or 'message'
        colors: Color scheme dict
    """
    if not interrupt_data:
        return None

    message = interrupt_data.get("message", "The agent needs your input to continue.")
    action_requests = interrupt_data.get("action_requests", [])

    children = [
        html.Div([
            html.Span("Action Required", className="interrupt-title", style={
                "fontSize": "14px",
                "fontWeight": "600",
                "textTransform": "uppercase",
                "letterSpacing": "0.5px",
            })
        ], style={"marginBottom": "12px"}),
        html.P(message, className="interrupt-message", style={
            "fontSize": "15px",
            "marginBottom": "15px",
        })
    ]

    # Show action requests if any
    if action_requests:
        for i, action in enumerate(action_requests):
            action_tool = action.get("tool", "")
            action_args = action.get("args", {})

            action_children = [
                html.Span("Tool: ", className="interrupt-tool-label", style={
                    "fontSize": "14px",
                }),
                html.Span(f"{action_tool}", className="interrupt-tool-name", style={
                    "fontSize": "15px",
                    "fontWeight": "600",
                    "fontFamily": "'IBM Plex Mono', monospace",
                }),
            ]

            children.append(html.Div(action_children, style={"marginBottom": "10px"}))

            # Show args for bash command specifically
            if action_tool == "bash" and action_args:
                command = action_args.get("command", "")
                if command:
                    children.append(html.Div([
                        html.Span("Command: ", className="interrupt-tool-label", style={
                            "fontSize": "14px",
                        }),
                        html.Pre(command, className="interrupt-command", style={
                            "fontSize": "15px",
                            "fontFamily": "'IBM Plex Mono', monospace",
                            "padding": "10px 15px",
                            "borderRadius": "5px",
                            "margin": "5px 0 15px 0",
                            "whiteSpace": "pre-wrap",
                            "wordBreak": "break-all",
                        })
                    ]))
            elif action_args:
                # Show other args in a compact format
                args_str = json.dumps(action_args, indent=2)
                if len(args_str) > 200:
                    args_str = args_str[:200] + "..."
                children.append(html.Pre(args_str, className="interrupt-args", style={
                    "fontSize": "14px",
                    "fontFamily": "'IBM Plex Mono', monospace",
                    "padding": "10px",
                    "borderRadius": "5px",
                    "margin": "5px 0 15px 0",
                    "maxHeight": "125px",
                    "overflow": "auto",
                }))

    # Input field for response
    children.append(html.Div([
        dcc.Input(
            id="interrupt-input",
            type="text",
            placeholder="Type your response...",
            className="interrupt-input",
            style={
                "width": "100%",
                "padding": "12px 15px",
                "borderRadius": "5px",
                "fontSize": "16px",
                "marginBottom": "10px",
            }
        ),
        html.Div([
            html.Button("Approve", id="interrupt-approve-btn", n_clicks=0,
                className="interrupt-btn interrupt-btn-approve",
                style={"marginRight": "10px"}
            ),
            html.Button("Reject", id="interrupt-reject-btn", n_clicks=0,
                className="interrupt-btn interrupt-btn-reject",
                style={"marginRight": "10px"}
            ),
            html.Button("Edit", id="interrupt-edit-btn", n_clicks=0,
                className="interrupt-btn interrupt-btn-edit"
            ),
        ], style={"display": "flex"})
    ]))

    return html.Div(children, className="interrupt-container")


def _format_timestamp(iso_timestamp: str) -> str:
    """Format ISO timestamp to human-readable format."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        return dt.strftime("%b %d, %H:%M")
    except (ValueError, TypeError):
        return ""


def _get_type_badge(item_type: str) -> dmc.Badge:
    """Get a badge component for the item type."""
    type_colors = {
        "markdown": "gray",
        "dataframe": "blue",
        "matplotlib": "green",
        "image": "green",
        "plotly": "violet",
        "mermaid": "cyan",
        "pdf": "red",
        "error": "red",
    }
    type_labels = {
        "markdown": "Text",
        "dataframe": "Table",
        "matplotlib": "Chart",
        "image": "Image",
        "plotly": "Plot",
        "mermaid": "Diagram",
        "pdf": "PDF",
        "error": "Error",
    }
    color = type_colors.get(item_type, "gray")
    label = type_labels.get(item_type, item_type.title())
    return dmc.Badge(label, color=color, size="xs", variant="light")


def render_canvas_items(canvas_items: List[Dict], colors: Dict, collapsed_ids: Optional[List[str]] = None) -> html.Div:
    """Render all canvas items using CSS classes for theme awareness.

    Args:
        canvas_items: List of canvas item dictionaries
        colors: Color scheme dictionary
        collapsed_ids: List of item IDs that should be rendered collapsed
    """
    if collapsed_ids is None:
        collapsed_ids = []

    if not canvas_items:
        return html.Div([
            html.P("Canvas empty", className="canvas-empty-text", style={
                "textAlign": "center",
                "fontSize": "14px"
            }),
            html.P("Visualizations and outputs appear here", className="canvas-empty-text", style={
                "textAlign": "center",
                "fontSize": "12px",
                "marginTop": "5px"
            })
        ], className="canvas-empty", style={
            "display": "flex",
            "flexDirection": "column",
            "alignItems": "center",
            "justifyContent": "center",
            "height": "100%",
            "padding": "25px"
        })

    rendered_items = []

    for i, item in enumerate(canvas_items):
        item_type = item.get("type", "unknown")
        item_id = item.get("id", f"canvas_item_{i}")
        is_collapsed = item_id in collapsed_ids
        title = item.get("title")
        created_at = item.get("created_at", "")

        # Build item header left side with collapse toggle, title, badge, and time
        header_left = [
            # Collapse/expand toggle - icon depends on collapsed state
            dmc.ActionIcon(
                DashIconify(icon="mdi:chevron-right" if is_collapsed else "mdi:chevron-down", width=16),
                id={"type": "canvas-collapse-btn", "index": item_id},
                variant="subtle",
                color="gray",
                size="sm",
                className="canvas-collapse-btn",
            ),
        ]
        if title:
            header_left.append(
                dmc.Text(title, fw=600, size="sm", className="canvas-item-title-text")
            )
        header_left.append(_get_type_badge(item_type))
        if created_at:
            formatted_time = _format_timestamp(created_at)
            if formatted_time:
                header_left.append(
                    dmc.Text(formatted_time, size="xs", c="dimmed", className="canvas-item-time")
                )

        # Header right side with delete button (shows confirmation on first click)
        header_right = dmc.Group([
            # Delete button - first click shows confirm, second click deletes
            dmc.ActionIcon(
                DashIconify(icon="mdi:close", width=14),
                id={"type": "canvas-delete-btn", "index": item_id},
                variant="subtle",
                color="gray",
                size="sm",
                className="canvas-delete-btn",
            ),
        ], gap="xs")

        item_header = html.Div([
            dmc.Group(header_left, gap="xs"),
            header_right,
        ], className="canvas-item-header")

        # Render content based on type
        if item_type == "markdown":
            content = html.Div([
                dcc.Markdown(
                    item.get("data", ""),
                    className="canvas-markdown",
                    style={
                        "fontSize": "15px",
                        "lineHeight": "1.5",
                        "wordBreak": "break-word",
                        "overflowWrap": "break-word",
                    }
                )
            ], className="canvas-item-content canvas-item-markdown", style={"padding": "10px"})

        elif item_type == "dataframe":
            content = html.Div([
                dcc.Markdown(
                    item.get("html", ""),
                    dangerously_allow_html=True,
                    style={"fontSize": "14px"}
                )
            ], className="canvas-item-content canvas-item-dataframe", style={
                "overflowX": "auto",
                "padding": "10px",
            })

        elif item_type == "matplotlib" or item_type == "image":
            img_data = item.get("data", "")
            content = html.Div([
                html.Img(
                    src=f"data:image/png;base64,{img_data}",
                    style={
                        "maxWidth": "100%",
                        "width": "100%",
                        "height": "auto",
                        "borderRadius": "5px",
                        "objectFit": "contain",
                    }
                )
            ], className="canvas-item-content canvas-item-image", style={
                "textAlign": "center",
                "padding": "10px",
            })

        elif item_type == "plotly":
            fig_data = item.get("data", {})
            content = html.Div([
                dcc.Graph(
                    figure=fig_data,
                    style={"height": "400px", "width": "100%"},
                    responsive=True,
                    config={
                        "displayModeBar": True,
                        "displaylogo": False,
                        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                        "responsive": True,
                    }
                )
            ], className="canvas-item-content canvas-item-plotly")

        elif item_type == "mermaid":
            mermaid_code = item.get("data", "")
            content = html.Div([
                html.Div(
                    mermaid_code,
                    className="mermaid-diagram",
                    style={
                        "textAlign": "center",
                        "padding": "25px",
                        "width": "100%",
                        "overflow": "auto",
                        "whiteSpace": "pre",
                    }
                )
            ], className="canvas-item-content canvas-item-mermaid", style={
                "textAlign": "center",
                "overflow": "auto",
            })

        elif item_type == "pdf":
            pdf_data = item.get("data", "")
            mime_type = item.get("mime_type", "application/pdf")
            if not pdf_data:
                content = html.Div([
                    html.Div("Error: PDF data is empty or missing", style={"color": "red"})
                ], className="canvas-item-content canvas-item-pdf", style={"padding": "10px"})
            else:
                data_url = f"data:{mime_type};base64,{pdf_data}"
                # Use iframe instead of embed for better browser compatibility
                content = html.Div([
                    html.Iframe(
                        src=data_url,
                        style={
                            "width": "100%",
                            "height": "500px",
                            "border": "none",
                            "borderRadius": "5px",
                        }
                    )
                ], className="canvas-item-content canvas-item-pdf", style={
                    "padding": "10px",
                })

        else:
            # Unknown type
            content = html.Div([
                html.Code(
                    str(item),
                    className="canvas-code",
                    style={
                        "fontSize": "15px",
                        "display": "block",
                        "whiteSpace": "pre-wrap",
                        "wordBreak": "break-word",
                    }
                )
            ], className="canvas-item-content canvas-item-code", style={
                "overflow": "auto",
                "padding": "10px",
            })

        # Wrap content in collapsible container - respect collapsed state
        content_wrapper = html.Div(
            content,
            id={"type": "canvas-item-content", "index": item_id},
            className="canvas-item-content-wrapper",
            style={"display": "none" if is_collapsed else "block"}
        )

        # Wrap header and content in item container
        rendered_items.append(
            html.Div([
                item_header,
                content_wrapper,
            ], id={"type": "canvas-item", "index": item_id}, className="canvas-item-container", style={
                "border": "1px solid var(--mantine-color-default-border)",
                "borderRadius": "6px",
                "marginBottom": "12px",
                "overflow": "hidden",
                "background": "var(--mantine-color-body)",
            })
        )

    return html.Div(rendered_items, style={
        "maxWidth": "100%",
        "overflow": "hidden",
    })
