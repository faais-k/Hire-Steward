import React from 'react';

export interface ToastMessage {
  id: string;
  text: string;
  type: 'info' | 'success' | 'error' | 'warning';
}

interface ToastContainerProps {
  toasts: ToastMessage[];
}

export const ToastContainer: React.FC<ToastContainerProps> = ({ toasts }) => {
  return (
    <div id="toast-container" className="toast-container">
      {toasts.map((t) => (
        <div key={t.id} className={`toast-msg toast-${t.type}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
};
