const taskSequence = [
    { id: 'repetitive', title: 'Tremor Test', text: 'aaaaa jjjjj rrrrr ppppp' },
    { id: 'standard', title: 'Baseline Test', text: 'The quick brown fox jumps over the lazy dog.' },
    { id: 'random', title: 'Natural Rhythm Test', text: 'Tell us about what you ate for breakfast today.' }
];

let currentStep = 0;
let startTime = null;
let keyLog = [];
let activeKeys = {};

const targetTextDisplay = document.getElementById('target-text');
const inputField = document.getElementById('input-field');
const taskTitleDisplay = document.getElementById('task-title');
const currentStepDisplay = document.getElementById('current-step');
const progressBar = document.getElementById('progress-bar');
const saveStatus = document.getElementById('save-status');

function initTask(index) {
    const task = taskSequence[index];
    
    taskTitleDisplay.innerText = task.title;
    targetTextDisplay.innerText = task.text;
    currentStepDisplay.innerText = index + 1;
    
    const progressPercent = (index / taskSequence.length) * 100;
    progressBar.style.width = `${progressPercent}%`;

    inputField.value = "";
    inputField.disabled = false;
    inputField.focus();
    keyLog = [];
    startTime = null;
    saveStatus.innerText = "Type the text above to proceed.";
}

inputField.addEventListener('keydown', (e) => {
    if (!startTime) startTime = performance.now();
    if (activeKeys[e.code]) return; // Block auto-repeat

    activeKeys[e.code] = {
        key: e.key,
        pressTime: (performance.now() - startTime) / 1000
    };
});

inputField.addEventListener('keyup', (e) => {
    if (activeKeys[e.code]) {
        const releaseTime = (performance.now() - startTime) / 1000;
        const holdDuration = releaseTime - activeKeys[e.code].pressTime;

        const dataPoint = {
            task: taskSequence[currentStep].id,
            key: e.key,
            pressTime: activeKeys[e.code].pressTime.toFixed(6),
            releaseTime: releaseTime.toFixed(6),
            holdDuration: holdDuration.toFixed(6),
            isError: e.key !== targetTextDisplay.innerText[inputField.value.length - 1]
        };

        keyLog.push(dataPoint);
        delete activeKeys[e.code];

        if (currentStep < 2) {
            if (inputField.value.length >= targetTextDisplay.innerText.length) {
                autoSave();
            }
        } else {
            saveStatus.innerText = "Press 'Enter' when you are finished typing.";
            if (e.key === "Enter") {
                autoSave();
            }
        }
    }
});

function autoSave() {
    const mode = taskSequence[currentStep].id;
    localStorage.setItem(`session_${mode}_${Date.now()}`, JSON.stringify(keyLog));
    
    currentStep++;

    if (currentStep < taskSequence.length) {
        initTask(currentStep);
    } else {
        progressBar.style.width = `100%`;
        document.getElementById('typing-area').innerHTML = `
            <div style="text-align:center; padding: 50px;">
                <h1 style="color:var(--accent)">Session Complete.</h1>
                <p>Thank you! Your data has been securely saved for analysis.</p>
            </div>
        `;
        saveStatus.innerText = "";
    }
}

initTask(0);