// Render a launchd LaunchAgent that runs the night under caffeinate (Node port).
import { chmodSync, mkdirSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { gitRoot } from './run.mjs';

export function installScheduler(config, configPath) {
  const root = gitRoot(), home = homedir();
  const agentsDir = path.join(home, 'Library', 'LaunchAgents');
  const logs = path.join(home, 'Library', 'Logs', 'nightsweeper');
  const stateDir = path.join(root, '.nightsweeper');
  for (const d of [agentsDir, logs, stateDir]) mkdirSync(d, { recursive: true });

  const cli = fileURLToPath(new URL('../bin/nightsweeper.mjs', import.meta.url));
  const runSh = path.join(stateDir, 'run.sh');
  writeFileSync(runSh, `#!/bin/bash\nset -euo pipefail\ncd "${root}"\nexec caffeinate -is "${process.execPath}" "${cli}" run --config "${configPath}"\n`);
  chmodSync(runSh, 0o755);

  const { hour, minute } = config.schedule;
  const plist = path.join(agentsDir, 'com.nightsweeper.run.plist');
  writeFileSync(plist, `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.nightsweeper.run</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>${runSh}</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>${hour}</integer><key>Minute</key><integer>${minute}</integer></dict>
  <key>StandardOutPath</key><string>${path.join(logs, 'run.log')}</string>
  <key>StandardErrorPath</key><string>${path.join(logs, 'run.err')}</string>
  <key>RunAtLoad</key><false/>
</dict></plist>\n`);

  const wm = minute > 0 ? minute - 1 : 59, wh = minute > 0 ? hour : (hour + 23) % 24;
  console.log(`Wrote ${runSh}\nWrote ${plist}\n\nNext steps (run yourself):`);
  console.log(`  launchctl load ${plist}`);
  console.log(`  sudo pmset repeat wakeorpoweron MTWRFSU ${String(wh).padStart(2, '0')}:${String(wm).padStart(2, '0')}:00`);
}
