"""Every WhatsApp Web selector lives here. Unverified against the live site: adjust on drift."""

PANE_SIDE = "#pane-side"
QR_CANVAS = "canvas[aria-label*='QR' i], div[data-ref]"
CHAT_HEADER = "#main header"
CHAT_TITLE = "#main header span[dir='auto'][title], #main header span[dir='auto']"
GROUP_HINT = "#main header span[title*=',']"
MESSAGE_ROW = "#main div[data-id]"
MESSAGE_TEXT = "span.selectable-text"
PRE_PLAIN_ATTR = "data-pre-plain-text"
PRE_PLAIN_HOLDER = "[data-pre-plain-text]"
COMPOSE_BOX = "footer div[contenteditable='true']"

# Chat list rows. Verified against a real dump of the 2026 chat list:
# grid[aria-label="Chat list"] > row[data-testid="list-item-N"] > cell-frame-* parts.
ROW = "#pane-side [role='listitem'], #pane-side [role='row']"
ROW_TITLE = "[data-testid='cell-frame-title'] span[dir='auto'][title], span[dir='auto'][title]"
ROW_TITLE_CELL = "[data-testid='cell-frame-title']"
ROW_UNREAD = "[data-testid='icon-unread-count'], span[aria-label*='unread' i]"
ROW_PREVIEW = "[data-testid='cell-frame-secondary'], span[dir='ltr'], span.matched-text"
ROW_CLICK_TARGET = "[data-testid='cell-frame-container']"
# The row WhatsApp marks as the open chat. Used when the header title cannot be read.
ACTIVE_ROW_TITLE = (
    "#pane-side [aria-selected='true'] span[dir='auto'][title], "
    "#pane-side [aria-selected='true'] [data-testid='cell-frame-title'] span[title]"
)
# Any of these means a chat is open. Header selector is still unverified.
CHAT_OPEN = "#main, [data-testid='conversation-header']"
