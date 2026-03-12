const vscode = require('vscode');
const { LanguageClient, LanguageClientOptions, ServerOptions } = require('vscode-languageclient/node');
const path = require('path');
const fs = require('fs');

let client;

function findProjectRoot(filePath) {
    let dir = path.dirname(filePath);
    while (dir !== path.parse(dir).root) {
        if (fs.existsSync(path.join(dir, 'build.c5b'))) {
            return dir;
        }
        dir = path.dirname(dir);
    }
    return null;
}

function activate(context) {
    // 1. Language Server Setup
    let serverModule = path.join(context.extensionPath, 'server', 'server.py');
    let serverOptions = {
        command: 'python3',
        args: [serverModule]
    };
    let clientOptions = {
        documentSelector: [{ scheme: 'file', language: 'c5' }],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.c5')
        }
    };
    client = new LanguageClient('c5LanguageServer', 'C5 Language Server', serverOptions, clientOptions);
    client.start();

    // 2. Build Command Implementation
    let buildCommand = vscode.commands.registerCommand('c5.buildProject', () => {
        const activeEditor = vscode.window.activeTextEditor;
        if (!activeEditor) {
            vscode.window.showErrorMessage('No active C5 file to build.');
            return;
        }

        const filePath = activeEditor.document.fileName;
        const root = findProjectRoot(filePath) || path.dirname(filePath);

        // Create or reuse terminal
        let terminal = vscode.window.terminals.find(t => t.name === 'C5 Build');
        if (!terminal) {
            terminal = vscode.window.createTerminal('C5 Build');
        }

        terminal.show();
        // Change to the project root and run build
        terminal.sendText(`cd "${root}" && c5c --build`);
    });

    context.subscriptions.push(buildCommand);
}

function deactivate() {
    if (!client) return undefined;
    return client.stop();
}

module.exports = { activate, deactivate };
