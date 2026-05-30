// Example only: requires @github/copilot-sdk package and runtime setup.
// Mirrors the workspace .agent.md team for Copilot SDK sessions.

import { CopilotClient } from '@github/copilot-sdk';

async function main() {
  const client = new CopilotClient();
  await client.start();

  const session = await client.createSession({
    model: 'gpt-5.2',
    customAgents: [
      {
        name: 'coruscant-researcher',
        displayName: 'Coruscant AR Researcher',
        description: 'Read-only analysis of results.tsv and trend extraction',
        tools: ['grep', 'glob', 'view'],
        prompt:
          'Analyze Coruscant autoresearch history in results.tsv, find best score and trend, return concise structured output.',
      },
      {
        name: 'coruscant-proposer',
        displayName: 'Coruscant AR Proposer',
        description: 'Mutates bounded parameter block in train.py',
        tools: ['view', 'edit'],
        prompt:
          'Edit only parameter constants in CoruscantSim/autoresearch_planet/train.py within allowed ranges. Do not modify objective logic.',
      },
      {
        name: 'coruscant-runner',
        displayName: 'Coruscant AR Runner',
        description: 'Runs one experiment and extracts score and diagnostics',
        tools: ['view', 'bash'],
        prompt:
          'Run exactly one experiment command and extract score plus key metrics. Verify results.tsv append.',
      },
      {
        name: 'coruscant-judge',
        displayName: 'Coruscant AR Judge',
        description: 'Applies keep-or-revert score-only decision',
        tools: ['view', 'edit', 'grep'],
        prompt:
          'Compare new score with previous best from results.tsv; keep if improved else revert parameter block to best-known values.',
      },
      {
        name: 'coruscant-coordinator',
        displayName: 'Coruscant Autoresearch',
        description: 'Coordinates full autoresearch loop for Coruscant parameter tuning',
        tools: null,
        prompt:
          'Coordinate researcher -> proposer -> runner -> judge for each iteration. Optimize score with keep/revert policy.',
      },
    ],
    agent: 'coruscant-coordinator',
    onPermissionRequest: async () => ({ kind: 'approved' }),
  });

  const response = await session.sendAndWait({
    prompt:
      'Run 3 autoresearch iterations for CoruscantSim/autoresearch_planet with strict keep-or-revert by score.',
  });

  console.log(response);
  await client.stop();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
