import api from './api';

const ANONYMOUS_ID_KEY = 'lineuplines_anonymous_id';

function getAnonymousId() {
  let id = localStorage.getItem(ANONYMOUS_ID_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(ANONYMOUS_ID_KEY, id);
  }
  return id;
}

// Fire-and-forget usage tracking. Never throws — a tracking failure must
// never break the app.
export function trackEvent(eventType, metadata = null) {
  api
    .post('/events', {
      event_type: eventType,
      anonymous_id: getAnonymousId(),
      page: window.location.pathname,
      metadata,
    })
    .catch(() => {});
}
