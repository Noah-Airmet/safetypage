// The wall on the search page: first pages chosen by eye from contact sheets of the openly
// licensed PDFs. Each is drawn from a small copy in public/wall/, made by scripts/make_wall.sh
// from the snapshot's page images. To change the wall, edit this list and run the script.
// A document that has left the library, or is no longer openly licensed, drops out at build.
export const WALL = [
  'arxiv:2502.16320', 'nist:nist.ai.600-1', 'arxiv:2510.00938', 'arxiv:2406.18682', 'arxiv:2409.04822', 'arxiv:2512.09403',
  'arxiv:2601.23149', 'anthropic:claude-constitution', 'arxiv:2502.18862', 'arxiv:2602.07852', 'nist:2021-nist.ir.8312',
  'arxiv:2404.09656', 'arxiv:2506.09277', 'us-eop:americas-ai-action-plan', 'arxiv:2407.02646', 'arxiv:2402.02309',
  'arxiv:2602.08964', 'arxiv:2605.20286', 'arxiv:2502.16681', 'arxiv:2505.04673', 'arxiv:2607.15434', 'nist:2025-nist.ir.8556',
  'iasr:international-ai-safety-report-2026-executive-summary_1', 'nist:upgraded-20sonnet-publication-us', 'arxiv:2406.13662',
  'arxiv:2601.02377', 'arxiv:2512.20677', 'nist:nist.sp.1270', 'arxiv:2412.00967', 'arxiv:2311.17030',
  'iasr:international_ai_safety_report_2025_english', 'iasr:second-key-update-english', 'nist:nist.ai.200-2.ipd', 'arxiv:2501.18052',
  'arxiv:2402.09091', 'arxiv:2601.16644', 'nist:ai-800-1', 'arxiv:2412.06483', 'arxiv:2408.15221', 'nist:ai-100-2',
  'iasr:international-ai-safety-report-2026_1', 'nist:2025-nist.ir.8596.iprd', 'arxiv:2408.12664', 'arxiv:2510.07452',
  'nist:caisi-evaluation-deepseek-ai-models-report', 'nist:nist.ai.300-1.ipd', 'arxiv:2503.05613', 'arxiv:2305.15324', 'arxiv:2309.08600',
];
export const wallFile = (docId: string) => `/wall/${docId.replace(':', '-')}.webp`;
