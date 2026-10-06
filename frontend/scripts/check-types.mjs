import { readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import process from 'node:process';

const directory = mkdtempSync(join(tmpdir(), 'scopegate-types-'));
try {
  const output = join(directory, 'api.d.ts');
  const result = spawnSync(
    process.execPath,
    ['node_modules/openapi-typescript/bin/cli.js', '../specs/contracts/openapi.json', '-o', output],
    { encoding: 'utf8' },
  );
  if (result.status !== 0) {
    process.stderr.write(result.stderr || result.stdout || 'Contract type generation failed.\n');
    process.exitCode = result.status ?? 1;
  } else if (readFileSync(output, 'utf8') !== readFileSync('src/generated/api.d.ts', 'utf8')) {
    process.stderr.write(
      'Generated API types are stale. Run npm run types:generate and review the contract changes.\n',
    );
    process.exitCode = 1;
  } else {
    process.stdout.write('Generated API types match the canonical HTTP contract.\n');
  }
} finally {
  rmSync(directory, { recursive: true, force: true });
}
