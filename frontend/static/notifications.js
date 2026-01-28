const AppNotifications = (function() {
    let toastContainer = null;

    function getToastContainer() {
        if (!toastContainer || !document.body.contains(toastContainer)) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.style.cssText = `
                position: fixed;
                top: 20px;
                left: 50%;
                transform: translateX(-50%);
                z-index: 10000;
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 10px;
                pointer-events: none;
            `;
            document.body.appendChild(toastContainer);
        }
        return toastContainer;
    }

    const icons = {
        success: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" style="width:14px;height:14px;">
            <path d="M20 6L9 17l-5-5"/>
        </svg>`,
        error: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;">
            <path d="M18 6L6 18M6 6l12 12"/>
        </svg>`,
        warning: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px;">
            <path d="M12 9v4m0 4h.01M12 3l9.5 16.5H2.5L12 3z"/>
        </svg>`,
        info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 16v-4m0-4h.01"/>
        </svg>`
    };

    const titles = {
        success: 'Sucesso!',
        error: 'Erro!',
        warning: 'Atenção!',
        info: 'Informação'
    };

    const colors = {
        success: '#10b981',
        error: '#ef4444',
        warning: '#f59e0b',
        info: '#772B21'
    };

    function showToast(type, message, options = {}) {
        const container = getToastContainer();
        const duration = options.duration || 4000;
        const title = options.title || titles[type];
        const color = colors[type];

        const toast = document.createElement('div');
        toast.style.cssText = `
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
            padding: 16px 24px;
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 300px;
            max-width: 500px;
            pointer-events: auto;
            border-left: 4px solid ${color};
            animation: toastSlideIn 0.3s ease;
        `;

        toast.innerHTML = `
            <div style="width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;background:${color}20;color:${color};">
                ${icons[type]}
            </div>
            <div style="flex:1;">
                <div style="font-weight:600;font-size:14px;color:#1f2937;margin-bottom:2px;">${title}</div>
                <div style="font-size:13px;color:#6b7280;">${message}</div>
            </div>
            <button style="background:none;border:none;cursor:pointer;color:#6b7280;padding:4px;display:flex;align-items:center;justify-content:center;border-radius:4px;" onclick="this.parentElement.remove()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 6L6 18M6 6l12 12"/>
                </svg>
            </button>
        `;

        container.appendChild(toast);

        if (duration > 0) {
            setTimeout(() => {
                toast.style.animation = 'toastSlideOut 0.3s ease forwards';
                setTimeout(() => toast.remove(), 300);
            }, duration);
        }

        return toast;
    }

    function success(message, options = {}) {
        return showToast('success', message, options);
    }

    function error(message, options = {}) {
        return showToast('error', message, options);
    }

    function warning(message, options = {}) {
        return showToast('warning', message, options);
    }

    function info(message, options = {}) {
        return showToast('info', message, options);
    }

    function confirm(options = {}) {
        return new Promise((resolve) => {
            const title = options.title || 'Confirmar ação';
            const message = options.message || 'Tem certeza que deseja continuar?';
            const confirmText = options.confirmText || 'Confirmar';
            const cancelText = options.cancelText || 'Cancelar';
            const type = options.type || 'warning';
            const isDanger = type === 'danger';

            const iconColor = isDanger ? '#ef4444' : '#f59e0b';
            const iconBg = isDanger ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.1)';
            const btnColor = isDanger ? '#AC3631' : '#772B21';

            const iconSvg = isDanger 
                ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px;"><path d="M18 6L6 18M6 6l12 12"/></svg>`
                : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:24px;height:24px;"><path d="M12 9v4m0 4h.01M12 3l9.5 16.5H2.5L12 3z"/></svg>`;

            const overlay = document.createElement('div');
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10001;
                animation: fadeIn 0.2s ease;
            `;

            overlay.innerHTML = `
                <div style="background:white;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.2);max-width:400px;width:90%;animation:modalSlideIn 0.3s ease;">
                    <div style="padding:24px 24px 0;display:flex;align-items:center;gap:16px;">
                        <div style="width:48px;height:48px;border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;background:${iconBg};color:${iconColor};">
                            ${iconSvg}
                        </div>
                    </div>
                    <div style="padding:24px;">
                        <div style="font-size:18px;font-weight:600;color:#1f2937;margin-bottom:8px;">${title}</div>
                        <div style="font-size:14px;color:#6b7280;line-height:1.5;">${message}</div>
                    </div>
                    <div style="padding:0 24px 24px;display:flex;gap:12px;justify-content:flex-end;">
                        <button id="confirm-cancel" style="padding:10px 20px;border-radius:8px;font-size:14px;font-weight:500;cursor:pointer;min-width:100px;background:#f3f4f6;border:1px solid #e5e7eb;color:#374151;">
                            ${cancelText}
                        </button>
                        <button id="confirm-ok" style="padding:10px 20px;border-radius:8px;font-size:14px;font-weight:500;cursor:pointer;min-width:100px;background:${btnColor};border:none;color:white;">
                            ${confirmText}
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            const cancelBtn = overlay.querySelector('#confirm-cancel');
            const confirmBtn = overlay.querySelector('#confirm-ok');

            function close(result) {
                overlay.style.opacity = '0';
                overlay.style.transition = 'opacity 0.2s ease';
                setTimeout(() => {
                    overlay.remove();
                    resolve(result);
                }, 200);
            }

            cancelBtn.onclick = () => close(false);
            confirmBtn.onclick = () => close(true);

            overlay.onclick = (e) => {
                if (e.target === overlay) close(false);
            };

            document.addEventListener('keydown', function escHandler(e) {
                if (e.key === 'Escape') {
                    document.removeEventListener('keydown', escHandler);
                    close(false);
                }
            });

            confirmBtn.focus();
        });
    }

    const style = document.createElement('style');
    style.textContent = `
        @keyframes toastSlideIn {
            from { opacity: 0; transform: translateY(-20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes toastSlideOut {
            from { opacity: 1; transform: translateY(0); }
            to { opacity: 0; transform: translateY(-20px); }
        }
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        @keyframes modalSlideIn {
            from { opacity: 0; transform: scale(0.95) translateY(-10px); }
            to { opacity: 1; transform: scale(1) translateY(0); }
        }
    `;
    document.head.appendChild(style);

    return {
        success,
        error,
        warning,
        info,
        confirm,
        showToast
    };
})();

window.toast = AppNotifications;
