import { useState } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * Floating feedback button fixed to the bottom-right of every page.
 * Submits to POST /api/v1/feedback — the backend forwards via AWS SES.
 */
export default function FeedbackWidget() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState('');
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState('idle'); // 'idle' | 'submitting' | 'success' | 'error'

  const handleOpen = () => {
    setOpen(true);
    setStatus('idle');
  };

  const handleClose = () => {
    setOpen(false);
    setMessage('');
    setEmail('');
    setStatus('idle');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!message.trim()) return;

    setStatus('submitting');
    try {
      const res = await fetch('/api/v1/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: message.trim(),
          page: location.pathname,
          email: email.trim() || null,
        }),
      });

      if (!res.ok) throw new Error('Server error');
      setStatus('success');
      setMessage('');
      setEmail('');
    } catch {
      setStatus('error');
    }
  };

  return (
    <>
      {/* Floating trigger button */}
      <button
        onClick={handleOpen}
        aria-label="Send feedback"
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 bg-sleeper-blue hover:bg-[#00a3e0] text-white text-sm font-medium px-4 py-2.5 rounded-full shadow-lg shadow-sleeper-blue/30 hover:shadow-sleeper-blue/50 transition-all"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clipRule="evenodd" />
        </svg>
        Feedback
      </button>

      {/* Modal overlay */}
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-end p-6"
          onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
        >
          {/* Backdrop */}
          <div className="fixed inset-0 bg-black/40" onClick={handleClose} />

          {/* Modal panel */}
          <div className="relative z-10 w-full max-w-sm bg-sleeper-dark border border-sleeper-gray-700 rounded-2xl shadow-2xl p-6 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h3 className="text-white font-semibold text-base">Share your feedback</h3>
              <button
                onClick={handleClose}
                className="text-sleeper-gray-400 hover:text-white transition-colors p-1 rounded"
                aria-label="Close"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            </div>

            {status === 'success' ? (
              <div className="flex flex-col items-center gap-3 py-4 text-center">
                <div className="w-12 h-12 bg-sleeper-green/10 border border-sleeper-green/20 rounded-full flex items-center justify-center">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6 text-sleeper-green" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <p className="text-white font-medium">Thanks for the feedback!</p>
                <p className="text-sleeper-gray-400 text-sm">It helps make LineupLines better.</p>
                <button
                  onClick={handleClose}
                  className="mt-1 text-sleeper-blue hover:text-white text-sm transition-colors"
                >
                  Close
                </button>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                <div>
                  <label className="block text-sleeper-gray-400 text-xs mb-1.5 font-medium uppercase tracking-wide">
                    What&apos;s on your mind?
                  </label>
                  <textarea
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    placeholder="Bugs, ideas, missing features — anything helps."
                    rows={4}
                    required
                    className="w-full bg-sleeper-gray-900 border border-sleeper-gray-700 rounded-lg px-3 py-2.5 text-white text-sm placeholder-sleeper-gray-500 focus:outline-none focus:border-sleeper-blue focus:ring-1 focus:ring-sleeper-blue transition-colors resize-none"
                  />
                </div>

                <div>
                  <label className="block text-sleeper-gray-400 text-xs mb-1.5 font-medium uppercase tracking-wide">
                    Your email <span className="text-sleeper-gray-600 normal-case font-normal">(optional — if you want a reply)</span>
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full bg-sleeper-gray-900 border border-sleeper-gray-700 rounded-lg px-3 py-2.5 text-white text-sm placeholder-sleeper-gray-500 focus:outline-none focus:border-sleeper-blue focus:ring-1 focus:ring-sleeper-blue transition-colors"
                  />
                </div>

                {status === 'error' && (
                  <p className="text-sleeper-red text-xs">
                    Something went wrong. Please try again.
                  </p>
                )}

                <div className="flex gap-2 pt-1">
                  <button
                    type="button"
                    onClick={handleClose}
                    className="flex-1 text-sm font-medium text-sleeper-gray-400 hover:text-white px-4 py-2.5 rounded-lg border border-sleeper-gray-700 hover:bg-sleeper-gray-800 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={status === 'submitting' || !message.trim()}
                    className="flex-1 text-sm font-medium bg-sleeper-blue hover:bg-[#00a3e0] disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2.5 rounded-lg transition-colors"
                  >
                    {status === 'submitting' ? 'Sending…' : 'Send'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  );
}
