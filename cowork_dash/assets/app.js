// Theme handling - sync mermaid with DMC color scheme
(function initTheme() {
    function updateMermaidTheme(theme) {
        if (typeof mermaid !== 'undefined') {
            mermaid.initialize({
                startOnLoad: false,
                theme: theme === 'dark' ? 'dark' : 'default',
                securityLevel: 'loose',
                logLevel: 'error'
            });
            // Clear processed flag so diagrams re-render with new theme
            const mermaidDivs = document.querySelectorAll('.mermaid-diagram');
            mermaidDivs.forEach(function(div) {
                div.removeAttribute('data-processed');
            });
            // Re-render any existing mermaid diagrams
            renderMermaid();
        }
    }

    // Watch for DMC color scheme changes via MutationObserver
    function watchColorScheme() {
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'data-mantine-color-scheme') {
                    const scheme = document.documentElement.getAttribute('data-mantine-color-scheme');
                    updateMermaidTheme(scheme);
                }
            });
        });

        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-mantine-color-scheme']
        });

        // Initial theme check
        const initialScheme = document.documentElement.getAttribute('data-mantine-color-scheme');
        if (initialScheme) {
            updateMermaidTheme(initialScheme);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', watchColorScheme);
    } else {
        watchColorScheme();
    }
})();

// Initialize Mermaid
mermaid.initialize({
    startOnLoad: false,
    theme: 'default',
    securityLevel: 'loose',
    logLevel: 'error'
});

// Render mermaid diagrams
async function renderMermaid() {
    const mermaidDivs = document.querySelectorAll('.mermaid-diagram');

    for (const div of mermaidDivs) {
        if (!div.getAttribute('data-processed')) {
            // Get code from stored attribute (for re-renders) or from textContent (first render)
            let code = div.getAttribute('data-mermaid-code');
            if (!code) {
                code = div.textContent.trim();
                // Store original code for future re-renders (theme changes)
                div.setAttribute('data-mermaid-code', code);
            }
            div.setAttribute('data-processed', 'true');

            try {
                // Clear the div and create unique ID
                const id = 'mermaid-' + Math.random().toString(36).substr(2, 9);
                div.innerHTML = '';

                // Render mermaid
                const { svg } = await mermaid.render(id, code);
                div.innerHTML = svg;
            } catch (error) {
                console.error('Mermaid rendering error:', error);
                div.innerHTML = '<div style="color: #d93025; padding: 20px; text-align: left;">' +
                    '<strong>Mermaid Syntax Error:</strong><br>' +
                    '<code style="font-size: 12px;">' + error.message + '</code><br><br>' +
                    '<details><summary style="cursor: pointer;">View Code</summary>' +
                    '<pre style="background: #f5f5f5; padding: 10px; margin-top: 10px; overflow: auto;">' +
                    code + '</pre></details></div>';
            }
        }
    }
}

// Run mermaid on load and when content changes
window.addEventListener('load', renderMermaid);

// Use MutationObserver to detect when canvas content changes
// Check if observer already exists to prevent redeclaration errors
if (typeof window.mermaidObserver === 'undefined') {
    window.mermaidObserver = new MutationObserver(function(mutations) {
        renderMermaid();
    });

    // Start observing once the canvas is available - retry until found
    function attachMermaidObserver() {
        const canvasContent = document.getElementById('canvas-content');
        if (canvasContent) {
            window.mermaidObserver.observe(canvasContent, { childList: true, subtree: true });
            console.log('Mermaid observer attached to canvas-content');
            // Run initial render in case content is already there
            renderMermaid();
        } else {
            // Retry after a short delay
            setTimeout(attachMermaidObserver, 500);
        }
    }
    attachMermaidObserver();
}

// Prevent clicks on "Add to Canvas" buttons from toggling the collapsible
// We need to intercept the toggle event on the details element, not the click
(function initAddToCanvasButtons() {
    function setupButtonHandlers() {
        // Track if button was clicked to prevent details toggle
        let buttonClicked = false;

        // When button is clicked, set flag (uses capture to run first)
        document.addEventListener('click', function(e) {
            const button = e.target.closest('.add-to-canvas-btn');
            if (button) {
                buttonClicked = true;
                // Reset flag after a short delay to allow for the toggle event
                setTimeout(() => { buttonClicked = false; }, 50);
            }
        }, true);

        // Intercept the toggle event on details elements
        document.addEventListener('toggle', function(e) {
            if (buttonClicked && e.target.classList.contains('display-inline-container')) {
                // Button was clicked, prevent the toggle by reverting it
                // The toggle has already happened, so we need to undo it
                e.target.open = !e.target.open;
            }
        }, true);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupButtonHandlers);
    } else {
        setupButtonHandlers();
    }
})();

// Auto-scroll chat messages to bottom
(function initChatAutoScroll() {
    let chatMessages = null;

    function scrollToBottom() {
        if (chatMessages) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    function setupAutoScroll() {
        chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) {
            setTimeout(setupAutoScroll, 500);
            return;
        }

        // Watch for changes to chat messages
        const observer = new MutationObserver(function(mutations) {
            // Small delay to ensure DOM is updated
            setTimeout(scrollToBottom, 50);
        });

        observer.observe(chatMessages, {
            childList: true,
            subtree: true
        });

        console.log('Chat auto-scroll initialized');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupAutoScroll);
    } else {
        setupAutoScroll();
    }
})();

// Resizable split pane - improved reliability
(function initResizablePanes() {
    let isResizing = false;
    let container, chatPanel, resizeHandle, sidebar;

    function findElements() {
        container = document.getElementById('main-container');
        chatPanel = document.getElementById('chat-panel');
        resizeHandle = document.getElementById('resize-handle');
        sidebar = document.getElementById('sidebar-panel');

        return !!(resizeHandle && chatPanel && sidebar && container);
    }

    function handleMouseDown(e) {
        e.preventDefault();
        e.stopPropagation();
        isResizing = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        // Add a semi-transparent overlay to prevent interference
        const overlay = document.createElement('div');
        overlay.id = 'resize-overlay';
        overlay.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 9999; cursor: col-resize;';
        document.body.appendChild(overlay);
    }

    function handleMouseMove(e) {
        if (!isResizing) return;
        e.preventDefault();

        const containerRect = container.getBoundingClientRect();
        const containerWidth = containerRect.width;
        const offsetX = e.clientX - containerRect.left;
        const chatWidth = (offsetX / containerWidth) * 100;

        // Constrain between 30% and 70%
        if (chatWidth >= 30 && chatWidth <= 70) {
            chatPanel.style.flex = `0 0 ${chatWidth}%`;
            sidebar.style.flex = `0 0 ${100 - chatWidth}%`;
        }
    }

    function handleMouseUp() {
        if (isResizing) {
            isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            // Remove the overlay
            const overlay = document.getElementById('resize-overlay');
            if (overlay) {
                overlay.remove();
            }
        }
    }

    function setupResizing() {
        if (!findElements()) {
            console.log('Resize elements not found, retrying...');
            setTimeout(setupResizing, 500);
            return;
        }

        // Remove any existing listeners to prevent duplicates
        resizeHandle.removeEventListener('mousedown', handleMouseDown);
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);

        // Add event listeners
        resizeHandle.addEventListener('mousedown', handleMouseDown);
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);

        console.log('Resize functionality initialized');
    }

    // Initialize on load and after a short delay to ensure DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupResizing);
    } else {
        setupResizing();
    }

    // Also try after window load
    window.addEventListener('load', function() {
        setTimeout(setupResizing, 100);
    });
})();
