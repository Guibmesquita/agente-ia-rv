function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');
    sidebar.classList.toggle('collapsed');
    if (sidebar.classList.contains('collapsed')) {
        mainContent.style.marginLeft = 'var(--sidebar-collapsed)';
    } else {
        mainContent.style.marginLeft = 'var(--sidebar-width)';
    }
    localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
}

function applySavedSidebarState() {
    if (localStorage.getItem('sidebarCollapsed') === 'true') {
        document.getElementById('sidebar').classList.add('collapsed');
        document.getElementById('mainContent').style.marginLeft = 'var(--sidebar-collapsed)';
    }
}

document.addEventListener('DOMContentLoaded', applySavedSidebarState);
