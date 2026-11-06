const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("sidebar");
const overlay = document.getElementById("sidebarOverlay");

function toggleMenu() {
    sidebar.classList.toggle("open");
    overlay.classList.toggle("show");
}

if (menuButton) menuButton.addEventListener("click", toggleMenu);
if (overlay) overlay.addEventListener("click", toggleMenu);

document.querySelectorAll(".message button").forEach((button) => {
    button.addEventListener("click", () => button.parentElement.remove());
});

const repeatCheckbox = document.querySelector("[name='repeat_weekly']");
const repeatUntilField = document.querySelector("[data-field='repeat_until']");
const weekdaysField = document.querySelector("[data-field='weekdays']");
if (repeatCheckbox && repeatUntilField && weekdaysField) {
    const syncRepeatField = () => {
        repeatUntilField.classList.toggle("field-muted", !repeatCheckbox.checked);
        weekdaysField.classList.toggle("field-muted", !repeatCheckbox.checked);
    };
    repeatCheckbox.addEventListener("change", syncRepeatField);
    syncRepeatField();
}

// Live countdown to the next game on the game-day panel.
document.querySelectorAll(".gh-countdown[data-kickoff]").forEach((box) => {
    const kickoff = new Date(box.dataset.kickoff).getTime();
    if (Number.isNaN(kickoff)) return;
    const cells = {};
    box.querySelectorAll("[data-unit]").forEach((el) => { cells[el.dataset.unit] = el; });
    const tick = () => {
        let left = Math.max(0, Math.floor((kickoff - Date.now()) / 1000));
        if (left === 0) {
            // Kickoff: reload once so the panel switches to "Live now".
            clearInterval(timer);
            setTimeout(() => window.location.reload(), 1500);
        }
        const d = Math.floor(left / 86400); left -= d * 86400;
        const h = Math.floor(left / 3600); left -= h * 3600;
        const m = Math.floor(left / 60);
        const s = left - m * 60;
        cells.d.textContent = d;
        cells.h.textContent = String(h).padStart(2, "0");
        cells.m.textContent = String(m).padStart(2, "0");
        cells.s.textContent = String(s).padStart(2, "0");
    };
    const timer = setInterval(tick, 1000);
    tick();
});
