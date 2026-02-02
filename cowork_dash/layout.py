"""Layout components for DeepAgent Dash."""

from dash import html, dcc
import dash_mantine_components as dmc
from dash_iconify import DashIconify

from .file_utils import build_file_tree, render_file_tree
from .config import WELCOME_MESSAGE as DEFAULT_WELCOME_MESSAGE


def create_layout(workspace_root, app_title, app_subtitle, colors, styles, agent, welcome_message=None):
    """
    Create the app layout with current configuration.

    Args:
        workspace_root: Path to workspace directory (or None for virtual FS mode)
        app_title: Application title
        app_subtitle: Application subtitle
        colors: Color scheme dictionary
        styles: Styles dictionary
        agent: Agent instance (or None)
        welcome_message: Optional welcome message (uses default if not provided)

    Returns:
        Dash layout component
    """
    # Use provided welcome message or fall back to default
    message = welcome_message if welcome_message is not None else DEFAULT_WELCOME_MESSAGE

    # Build initial file tree (empty if workspace_root is None for virtual FS mode)
    if workspace_root is not None:
        initial_file_tree = render_file_tree(build_file_tree(workspace_root, workspace_root), colors, styles)
    else:
        initial_file_tree = []  # Empty tree for virtual FS - will be populated per-session

    return dmc.MantineProvider(
        id="mantine-provider",
        forceColorScheme="light",
        children=[
            # State stores
            dcc.Store(id="chat-history", data=[{
                "role": "assistant",
                "content": message
            }]),
            dcc.Store(id="pending-message", data=None),
            dcc.Store(id="skip-history-render", data=False),  # Flag to skip display_initial_messages render
            dcc.Store(id="session-initialized", data=False),  # Flag to track if session has been initialized
            dcc.Store(id="session-id", data=None, storage_type="session"),  # Session ID for virtual FS isolation
            dcc.Store(id="expanded-folders", data=[]),
            dcc.Store(id="file-to-view", data=None),
            dcc.Store(id="file-click-tracker", data={}),
            dcc.Store(id="csv-pagination", data={"page": 0, "total_pages": 0, "rows_per_page": 50}),
            dcc.Store(id="theme-store", data="light", storage_type="local"),
            dcc.Store(id="current-workspace-path", data=""),  # Relative path from original workspace root
            dcc.Store(id="collapsed-canvas-items", data=[]),  # Track which canvas items are collapsed
            dcc.Download(id="file-download"),

            # Interval for polling agent updates (disabled by default)
            dcc.Interval(id="poll-interval", interval=250, disabled=True),

            # File viewer modal
            dmc.Modal(
                id="file-modal",
                title="",
                size="xl",
                children=[
                    html.Div(id="modal-content"),
                    html.Div([
                        dmc.Button(
                            "Download",
                            id="modal-download-btn",
                            variant="outline",
                            color="blue",
                            style={"marginTop": "16px"}
                        )
                    ], style={"textAlign": "right"})
                ],
                opened=False,
            ),

            # Create folder modal
            dmc.Modal(
                id="create-folder-modal",
                title="Create New Folder",
                size="sm",
                children=[
                    dmc.TextInput(
                        id="new-folder-name",
                        label="Folder name",
                        placeholder="Enter folder name",
                        style={"marginBottom": "16px"},
                    ),
                    dmc.Text(id="create-folder-error", c="red", size="sm", style={"marginBottom": "8px"}),
                    dmc.Group([
                        dmc.Button("Cancel", id="cancel-folder-btn", variant="outline", color="gray"),
                        dmc.Button("Create", id="confirm-folder-btn", color="blue"),
                    ], justify="flex-end"),
                ],
                opened=False,
            ),

            # Delete canvas item confirmation modal
            dmc.Modal(
                id="delete-canvas-item-modal",
                title="Delete Canvas Item",
                size="sm",
                children=[
                    dmc.Text("Are you sure you want to delete this canvas item? This action cannot be undone.",
                             size="sm", style={"marginBottom": "16px"}),
                    dmc.Group([
                        dmc.Button("Cancel", id="cancel-delete-canvas-btn", variant="outline", color="gray"),
                        dmc.Button("Delete", id="confirm-delete-canvas-btn", color="red"),
                    ], justify="flex-end"),
                ],
                opened=False,
            ),

            # Store for canvas item ID pending deletion
            dcc.Store(id="delete-canvas-item-id", data=None),

            # Clear canvas confirmation modal
            dmc.Modal(
                id="clear-canvas-modal",
                title="Clear Canvas",
                size="sm",
                children=[
                    dmc.Text("Are you sure you want to clear the entire canvas? The current canvas will be archived with a timestamp.",
                             size="sm", style={"marginBottom": "16px"}),
                    dmc.Group([
                        dmc.Button("Cancel", id="cancel-clear-canvas-btn", variant="outline", color="gray"),
                        dmc.Button("Clear", id="confirm-clear-canvas-btn", color="red"),
                    ], justify="flex-end"),
                ],
                opened=False,
            ),

            html.Div([
                # Compact Header
                html.Header([
                    html.Div([
                        html.Div([
                            html.H1(app_title or "DeepAgent Dash", id="app-title", style={
                                "fontSize": "17px", "fontWeight": "600", "margin": "0",
                            }),
                            html.Span(app_subtitle or "AI-Powered Workspace", id="app-subtitle", style={
                                "fontSize": "14px", "color": "var(--mantine-color-dimmed)", "marginLeft": "10px",
                            })
                        ], style={"display": "flex", "alignItems": "baseline"}),
                        html.Div([
                            dmc.ActionIcon(
                                DashIconify(icon="radix-icons:moon", width=18),
                                id="theme-toggle-btn",
                                variant="subtle",
                                color="gray",
                                size="md",
                                radius="sm",
                                style={"marginRight": "8px"},
                            ),
                            html.Div(style={
                                "width": "8px", "height": "8px",
                                "borderRadius": "50%",
                                "background": "var(--mantine-color-green-6)" if agent else "var(--mantine-color-red-6)",
                                "marginRight": "5px",
                            }, id="agent-status-indicator"),
                            dmc.Text("Ready" if agent else "No Agent", size="sm", c="dimmed", id="agent-status-text")
                        ], style={"display": "flex", "alignItems": "center"})
                    ], style={
                        "display": "flex", "justifyContent": "space-between",
                        "alignItems": "center", "width": "100%",
                        "padding": "0 12px",
                    })
                ], id="header", style={
                    "background": "var(--mantine-color-body)",
                    "borderBottom": "1px solid var(--mantine-color-default-border)",
                    "padding": "8px 0",
                }),

            # Main content
            html.Main([
                # Chat panel (no header)
                html.Div([
                    # Messages
                    html.Div(id="chat-messages", style={
                        "flex": "1", "overflowY": "auto", "padding": "15px",
                        "display": "flex", "flexDirection": "column", "gap": "10px",
                    }),

                    # Compact Input
                    html.Div([
                        dmc.TextInput(
                            id="chat-input",
                            placeholder="Type a message...",
                            className="chat-input",
                            style={"flex": "1"},
                            size="md",
                        ),
                        dmc.Button("Send", id="send-btn", className="send-btn", size="md"),
                        dmc.ActionIcon(
                            DashIconify(icon="mdi:stop", width=20),
                            id="stop-btn",
                            variant="filled",
                            color="red",
                            size="lg",
                            radius="sm",
                            style={"display": "none"},  # Hidden by default, shown when agent is running
                        ),
                    ], id="chat-input-area", style={
                        "display": "flex", "gap": "8px", "padding": "10px 15px",
                        "borderTop": "1px solid var(--mantine-color-default-border)",
                        "background": "var(--mantine-color-body)",
                    }),
                ], id="chat-panel", style={
                    "flex": "3", "display": "flex", "flexDirection": "column",
                    "background": "var(--mantine-color-body)", "minWidth": "0",
                }),

                # Resize handle
                html.Div(id="resize-handle", className="resize-handle", style={
                    "width": "3px",
                    "cursor": "col-resize",
                    "background": "transparent",
                    "flexShrink": "0",
                }),

                # Sidebar (Files/Canvas toggle)
                html.Div([
                    # Compact header with toggle
                    html.Div([
                        dmc.SegmentedControl(
                            id="sidebar-view-toggle",
                            data=[
                                {"value": "files", "label": "Files"},
                                {"value": "canvas", "label": "Canvas"},
                            ],
                            value="files",
                            size="sm",
                        ),
                        dmc.Group([
                            dmc.ActionIcon(
                                DashIconify(icon="mdi:folder-plus-outline", width=18),
                                id="create-folder-btn",
                                variant="default",
                                size="md",
                            ),
                            dcc.Upload(
                                id="file-upload-sidebar",
                                children=dmc.ActionIcon(
                                    DashIconify(icon="mdi:file-upload-outline", width=18),
                                    id="upload-btn",
                                    variant="default",
                                    size="md",
                                ),
                                multiple=True,
                            ),
                            dmc.ActionIcon(
                                DashIconify(icon="mdi:console", width=18),
                                id="open-terminal-btn",
                                variant="default",
                                size="md",
                            ),
                            dmc.ActionIcon(
                                DashIconify(icon="mdi:refresh", width=18),
                                id="refresh-btn",
                                variant="default",
                                size="md",
                            ),
                        ], id="files-actions", gap=5)
                    ], id="sidebar-header", style={
                        "display": "flex", "justifyContent": "space-between",
                        "alignItems": "center", "padding": "8px 12px",
                        "borderBottom": "1px solid var(--mantine-color-default-border)",
                    }),

                    # Files view
                    html.Div([
                        # Workspace path breadcrumb navigation
                        html.Div([
                            html.Div(id="workspace-breadcrumb", children=[
                                html.Span([
                                    DashIconify(icon="mdi:home", width=14, style={"marginRight": "4px"}),
                                    "root"
                                ], id="breadcrumb-root", className="breadcrumb-item breadcrumb-clickable", style={
                                    "display": "inline-flex",
                                    "alignItems": "center",
                                    "cursor": "pointer",
                                    "padding": "2px 6px",
                                    "borderRadius": "3px",
                                }),
                            ], style={
                                "display": "flex",
                                "alignItems": "center",
                                "flexWrap": "wrap",
                                "gap": "2px",
                                "fontSize": "13px",
                            }),
                        ], className="breadcrumb-bar", style={
                            "padding": "6px 10px",
                            "borderBottom": "1px solid var(--mantine-color-default-border)",
                        }),
                        html.Div(
                            id="file-tree",
                            children=initial_file_tree,
                            style={
                                "flex": "1",
                                "overflowY": "auto",
                                "minHeight": "0",
                            }
                        ),
                    ], id="files-view", style={
                        "flex": "1",
                        "minHeight": "0",
                        "display": "flex",
                        "flexDirection": "column",
                    }),

                    # Canvas view (hidden by default)
                    html.Div([
                        html.Div(id="canvas-content", style={
                            "flex": "1",
                            "minHeight": "0",
                            "overflowY": "auto",
                            "padding": "15px",
                            "background": "var(--mantine-color-body)",
                        }),
                        # Canvas action button
                        dmc.Group([
                            dmc.Button("Clear", id="clear-canvas-btn", size="sm", color="red", variant="light"),
                        ], id="canvas-actions", justify="center", style={
                            "padding": "8px 15px",
                            "borderTop": "1px solid var(--mantine-color-default-border)",
                            "background": "var(--mantine-color-body)",
                        })
                    ], id="canvas-view", style={
                        "flex": "1",
                        "minHeight": "0",
                        "display": "none",
                        "flexDirection": "column",
                        "overflow": "hidden"
                    }),
                ], id="sidebar-panel", style={
                    "flex": "1",
                    "minWidth": "0",
                    "minHeight": "0",
                    "display": "flex",
                    "flexDirection": "column",
                    "background": "var(--mantine-color-body)",
                    "borderLeft": "1px solid var(--mantine-color-default-border)",
                }),
            ], id="main-container", style={"display": "flex", "flex": "1", "overflow": "hidden"}),
        ], id="app-container", style={"display": "flex", "flexDirection": "column", "height": "100vh"})
    ])
