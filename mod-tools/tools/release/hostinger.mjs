// Execute reviewed Hostinger MCP requests using the existing local connection.
// Credentials stay in the user's MCP config and never enter release artifacts.
// Usage: node tools/release/hostinger.mjs requests.json results.json
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const config = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.claude.json'), 'utf8'));
const cfg = config.mcpServers['hostinger-api'];
const server = path.join(path.dirname(cfg.command), 'node_modules', 'hostinger-api-mcp');
const sdk = path.join(server, 'node_modules/@modelcontextprotocol/sdk/dist/esm');
const { Client } = await import(pathToFileURL(path.join(sdk, 'client/index.js')));
const { StdioClientTransport } = await import(pathToFileURL(path.join(sdk, 'client/stdio.js')));
const client = new Client({ name: 'ffr-release', version: '1.0.0' });
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [path.join(server, 'server.js')],
  env: { ...process.env, ...cfg.env, DEBUG: 'false' },
  stderr: 'pipe',
});
const requests = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const results = [];
try {
  await client.connect(transport);
  // Drain diagnostics without copying credentials or internal upload URLs into logs.
  transport.stderr?.on('data', () => {});
  for (const request of Array.isArray(requests) ? requests : [requests]) {
    console.log(JSON.stringify({ state: 'starting', tool: request.name, domain: request.arguments?.domain }));
    const response = await client.callTool(request, undefined, { timeout: 600000 });
    results.push({ request, response, completedAt: new Date().toISOString() });
    fs.writeFileSync(process.argv[3], JSON.stringify(results, null, 2));
    console.log(JSON.stringify({ state: response.isError ? 'failed' : 'returned', tool: request.name, domain: request.arguments?.domain }));
    if (response.isError) throw new Error('Hostinger request failed; inspect the saved response before retrying.');
    if (request.name === 'hosting_deployStaticWebsite') {
      const body = JSON.parse(response.content.find(c => c.type === 'text').text);
      if (body.upload?.status !== 'success' || body.deploy?.status !== 'success') {
        throw new Error('Hostinger did not accept the complete deployment; inspect the saved response.');
      }
    }
    if (request.name === 'hosting_createWebsiteV1' && process.argv.includes('--wait-websites')) {
      let ready = false;
      // Site creation is asynchronous. Let one finish before queuing another;
      // otherwise Hostinger can accept requests that never become websites.
      for (let attempt = 0; attempt < 12 && !ready; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 10000));
        const check = await client.callTool({ name: 'hosting_listWebsitesV1', arguments: { domain: request.arguments.domain } });
        if (check.isError) throw new Error('Could not verify the new website');
        const data = JSON.parse(check.content.find(c => c.type === 'text').text);
        ready = data.data?.some(s => s.domain === request.arguments.domain && s.is_enabled);
      }
      if (!ready) throw new Error('Website provisioning is still incomplete; inspect its status before retrying.');
      console.log(JSON.stringify({ state: 'ready', domain: request.arguments.domain }));
    }
  }
} finally {
  await client.close();
}
