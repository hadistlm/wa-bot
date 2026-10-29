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

# Chat list rows. Unverified against the live site.
ROW = "#pane-side [role='listitem'], #pane-side [role='row']"
ROW_TITLE = "span[dir='auto'][title]"
ROW_UNREAD = "span[aria-label*='unread' i]"
ROW_PREVIEW = "span[dir='ltr'], span.matched-text"
