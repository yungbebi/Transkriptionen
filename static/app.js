const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');
const filesList = document.getElementById('files-list');
const logsContainer = document.getElementById('logs');

// Drag and drop
['dragenter', 'dragover', 'dragleave', 'drop'].forEach(event => {
    dropzone.addEventListener(event, (e) => {
        e.preventDefault();
        e.stopPropagation();
    });
});

['dragenter', 'dragover'].forEach(event => {
    dropzone.addEventListener(event, () => dropzone.classList.add('drag'));
});

['dragleave', 'drop'].forEach(event => {
    dropzone.addEventListener(event, () => dropzone.classList.remove('drag'));
});

dropzone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    fileInput.files = files;
    uploadFiles(files);
});

dropzone.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', () => {
    uploadFiles(fileInput.files);
});

function uploadFiles(files) {
    for (let file of files) {
        const formData = new FormData();
        formData.append('file', file);

        fetch('/upload', {
            method: 'POST',
            body: formData
        }).then(r => r.json()).then(data => {
            if (data.success) {
                loadFileList();
            }
        });
    }
}

function transcribeFile(filename, button) {
    button.disabled = true;
    button.style.display = 'none';

    // Show stop button
    const stopBtn = document.getElementById(`stop-${filename}`);
    if (stopBtn) stopBtn.style.display = 'inline-block';

    const status = document.createElement('span');
    status.className = 'status';
    status.innerHTML = '<span class="spinner"></span> Transcribing...';
    button.parentNode.insertBefore(status, button.nextSibling);

    fetch('/transcribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename })
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                status.innerHTML = '✓ Done';
                status.classList.add('done');
                if (stopBtn) stopBtn.style.display = 'none';
                setTimeout(loadFileList, 1000);
            } else {
                status.innerHTML = `✗ ${data.error || 'Failed'}`;
                status.classList.add('error');
                status.style.maxWidth = '300px';
                status.style.wordBreak = 'break-word';
                if (stopBtn) stopBtn.style.display = 'none';
                button.style.display = 'inline-block';
            }
            button.disabled = false;
        })
        .catch(e => {
            status.innerHTML = `✗ ${e.message}`;
            status.classList.add('error');
            if (stopBtn) stopBtn.style.display = 'none';
            button.style.display = 'inline-block';
            button.disabled = false;
        });
}

function viewTranscript(filename) {
    fetch(`/view/${filename}`)
        .then(r => r.text())
        .then(html => {
            const w = window.open('');
            w.document.write(html);
            w.document.close();
        });
}

function deleteFile(filename) {
    if (confirm(`Delete transcript for ${filename}?`)) {
        fetch('/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename })
        }).then(r => r.json()).then(() => loadFileList());
    }
}

function stopTranscription(filename) {
    fetch('/stop/' + filename, {
        method: 'POST'
    }).then(() => {
        const btn = document.getElementById(`btn-${filename}`);
        const stopBtn = document.getElementById(`stop-${filename}`);
        if (btn) btn.style.display = 'inline-block';
        if (stopBtn) stopBtn.style.display = 'none';
    });
}

function loadFileList() {
    fetch('/files')
        .then(r => r.json())
        .then(data => {
            filesList.innerHTML = '';
            if (data.files.length === 0) {
                filesList.innerHTML = '<p style="grid-column: 1/-1; text-align: center; color: #999;">No audio files yet</p>';
                return;
            }

            for (let f of data.files) {
                const item = document.createElement('div');
                item.className = 'file-item';
                item.id = `file-${f.name}`;

                const nameEl = document.createElement('div');
                nameEl.className = 'file-name';
                nameEl.textContent = f.name;

                const infoEl = document.createElement('div');
                infoEl.className = 'file-info';
                infoEl.textContent = `${(f.size / 1024 / 1024).toFixed(2)} MB`;

                const actionsEl = document.createElement('div');
                actionsEl.className = 'file-actions';

                if (f.transcribed) {
                    actionsEl.innerHTML = `
                        <span style="color: #28a745;">✓ Transcribed (${(f.transcript_size / 1024).toFixed(1)} KB)</span>
                        <button class="btn-view" onclick="viewTranscript('${f.name}')">View</button>
                        <button class="btn-delete" onclick="deleteFile('${f.name}')">Delete Transcript</button>
                    `;
                } else {
                    actionsEl.innerHTML = `
                        <button class="btn-transcribe" id="btn-${f.name}" onclick="transcribeFile('${f.name}', this)">Transcribe</button>
                        <button class="btn-stop" id="stop-${f.name}" style="display:none;" onclick="stopTranscription('${f.name}')">Stop</button>
                    `;
                }

                item.appendChild(nameEl);
                item.appendChild(infoEl);
                item.appendChild(actionsEl);
                filesList.appendChild(item);
            }
        });
}

function streamLogs() {
    const eventSource = new EventSource('/logs');

    eventSource.onmessage = (event) => {
        const log = JSON.parse(event.data);
        const entry = document.createElement('div');
        entry.className = 'log-entry';

        const time = new Date(log.timestamp).toLocaleTimeString();
        let logClass = 'log-info';

        if (log.message.includes('Success') || log.message.includes('✓')) {
            logClass = 'log-success';
        } else if (log.message.includes('Failed') || log.message.includes('Error') || log.message.includes('✗')) {
            logClass = 'log-error';
        }

        entry.innerHTML = `<span class="log-time">[${time}]</span><span class="${logClass}">${log.message}</span>`;
        logsContainer.appendChild(entry);
        logsContainer.scrollTop = logsContainer.scrollHeight;
    };

    eventSource.onerror = () => {
        eventSource.close();
        setTimeout(streamLogs, 3000);
    };
}

// Initialize
loadFileList();
streamLogs();
