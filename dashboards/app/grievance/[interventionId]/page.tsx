'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';

export default function GrievancePage() {
  const params = useParams();
  const interventionId = params.interventionId as string;

  const [message, setMessage] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    if (!message.trim()) {
      setError('Please enter your query before submitting.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const res = await fetch('/api/grievances/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intervention_id: interventionId, message: message.trim() }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || 'Something went wrong. Please try again.');
        return;
      }

      setSubmitted(true);
    } catch (err) {
      setError('Network error. Please check your connection and try again.');
    } finally {
      setLoading(false);
    }
  };

  // ── Success Screen ──
  if (submitted) {
    return (
      <div style={{
        fontFamily: 'Helvetica, Arial, sans-serif',
        backgroundColor: '#f1f5f9',
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        margin: 0,
        padding: '20px',
      }}>
        <div style={{
          background: 'white',
          padding: '48px',
          borderRadius: '16px',
          boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)',
          textAlign: 'center',
          maxWidth: '480px',
          width: '100%',
          borderTop: '6px solid #16a34a',
        }}>
          <div style={{
            width: '72px', height: '72px',
            background: '#dcfce7',
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '0 auto 24px auto',
          }}>
            <svg viewBox="0 0 24 24" width="36" height="36" fill="#16a34a">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
            </svg>
          </div>
          <h1 style={{ color: '#16a34a', fontSize: '26px', margin: '0 0 12px 0', fontWeight: 700 }}>
            Grievance Submitted
          </h1>
          <p style={{ color: '#475569', fontSize: '16px', lineHeight: 1.6, margin: '0 0 16px 0' }}>
            Thank you. Your query has been submitted to our team. A credit officer will review it and get back to you shortly.
          </p>
          <p style={{
            fontSize: '13px',
            background: '#f8fafc',
            padding: '14px',
            borderRadius: '8px',
            border: '1px solid #e2e8f0',
            color: '#64748b',
          }}>
            You may now safely close this window.
          </p>
          <div style={{ marginTop: '32px', fontSize: '13px', color: '#94a3b8', borderTop: '1px solid #e2e8f0', paddingTop: '20px' }}>
            &copy; {new Date().getFullYear()} Sentinel AI Security Operations.
          </div>
        </div>
      </div>
    );
  }

  // ── Form Screen ──
  return (
    <div style={{
      fontFamily: 'Helvetica, Arial, sans-serif',
      backgroundColor: '#f1f5f9',
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      margin: 0,
      padding: '20px',
    }}>
      <div style={{
        background: 'white',
        borderRadius: '16px',
        boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)',
        maxWidth: '520px',
        width: '100%',
        overflow: 'hidden',
        borderTop: '6px solid #2563eb',
      }}>
        {/* Header */}
        <div style={{ padding: '32px 40px 0 40px' }}>
          <div style={{ fontSize: '20px', fontWeight: 700, color: '#1e293b', marginBottom: '8px' }}>
            Sentinel AI Security
          </div>
          <h1 style={{ fontSize: '24px', fontWeight: 700, color: '#0f172a', margin: '0 0 8px 0' }}>
            Submit a Grievance
          </h1>
          <p style={{ color: '#64748b', fontSize: '15px', margin: '0 0 28px 0', lineHeight: 1.6 }}>
            If you have any questions or concerns regarding your risk tier alert, please describe them below. Our credit officer team will review your query.
          </p>
        </div>

        {/* Form */}
        <div style={{ padding: '0 40px 40px 40px' }}>
          <div style={{ marginBottom: '20px' }}>
            <label style={{
              display: 'block',
              fontSize: '14px',
              fontWeight: 600,
              color: '#374151',
              marginBottom: '8px',
            }}>
              Your Query / Message <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <textarea
              value={message}
              onChange={e => { setMessage(e.target.value); setError(''); }}
              rows={6}
              placeholder="Describe your concern or question here..."
              style={{
                width: '100%',
                padding: '12px 14px',
                borderRadius: '8px',
                border: error ? '1.5px solid #ef4444' : '1.5px solid #e2e8f0',
                fontSize: '15px',
                color: '#0f172a',
                outline: 'none',
                resize: 'vertical',
                fontFamily: 'inherit',
                lineHeight: 1.6,
                boxSizing: 'border-box',
                transition: 'border-color 0.2s',
              }}
              onFocus={e => { if (!error) e.target.style.borderColor = '#2563eb'; }}
              onBlur={e => { if (!error) e.target.style.borderColor = '#e2e8f0'; }}
            />
            {error && (
              <p style={{ color: '#ef4444', fontSize: '13px', margin: '6px 0 0 0' }}>{error}</p>
            )}
          </div>

          <button
            onClick={handleSubmit}
            disabled={loading}
            style={{
              width: '100%',
              padding: '14px',
              backgroundColor: loading ? '#93c5fd' : '#2563eb',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              fontSize: '16px',
              fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              transition: 'background-color 0.2s',
            }}
          >
            {loading ? 'Submitting...' : 'Submit Grievance'}
          </button>

          <p style={{ textAlign: 'center', fontSize: '13px', color: '#94a3b8', marginTop: '16px' }}>
            Your response will be sent to our credit officer team.
          </p>
        </div>

        <div style={{
          borderTop: '1px solid #e2e8f0',
          padding: '20px 40px',
          textAlign: 'center',
          fontSize: '12px',
          color: '#94a3b8',
        }}>
          &copy; {new Date().getFullYear()} Sentinel AI Security Operations. All rights reserved.
        </div>
      </div>
    </div>
  );
}