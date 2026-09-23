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
