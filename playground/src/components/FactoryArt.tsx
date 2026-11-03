export function FactoryArt({
  kind,
  color = "#74829b",
  active = false,
}: {
  kind: string;
  color?: string;
  active?: boolean;
}) {
  return (
    <svg
      viewBox="0 0 160 112"
      className={`factory-art ${active ? "art-active" : ""}`}
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <pattern
          id={"hatch-" + kind}
          width="5"
          height="5"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(35)"
        >
          <path d="M0 0V5" stroke={color} strokeWidth=".7" opacity=".35" />
        </pattern>
      </defs>
      <path
        d="M13 76 77 48 147 76 147 88 82 111 13 89Z"
        fill="#f8fafc"
        stroke={color}
        strokeWidth="1.2"
      />
      <path
        d="M13 76 81 99 147 76V87L82 111 13 89Z"
        fill={`url(#hatch-${kind})`}
        stroke={color}
        strokeWidth="1.1"
      />
      <path
        d="M13 76 77 49 147 76 81 99Z"
        fill="white"
        stroke={color}
        strokeWidth="1.2"
      />
      <path
        d="M23 76 77 55 137 76 81 93Z"
        stroke={color}
        strokeDasharray="3 3"
        opacity=".35"
      />
      {kind === "document" || kind === "requirement" ? (
        <g stroke={color} strokeWidth="1.5" strokeLinejoin="round">
          <path d="m54 20 33-10 25 13v49L80 84 54 70Z" fill="#eaf0ff" />
          <path d="m54 20 26 14 32-11M80 34v50" />
          <path d="m61 31 13 7m-13 2 13 7m-13 2 13 7m12-12 18-6m-18 14 18-6m-18 14 18-6" />
          <path d="m40 52 12-4v23l-12 4Z" fill="white" />
          <path d="m115 45 12 6v24l-12-5Z" fill="white" />
        </g>
      ) : kind === "database" || kind === "entity" ? (
        <g stroke={color} strokeWidth="1.5" strokeLinejoin="round">
          <path d="m45 34 35-16 35 17-35 17Z" fill="#eef8f3" />
          <path d="M45 34v38l35 17V52Zm35 18v37l35-18V35" fill="white" />
          <path d="m52 29 28-13 30 15M80 18v32m-30 9 22 11m-22-2 22 11m15-20 21-11m-21 20 21-11m-21 20 21-11" />
          <path
            d="m45 34-10-8 34-16 11 8m35 17 12-8-35-17-12 8"
            fill="#f2fbf6"
          />
        </g>
      ) : kind === "api" ? (
        <g stroke={color} strokeWidth="1.5" strokeLinejoin="round">
          <path d="m54 29 27-12 29 14-28 13Z" fill="#fff3df" />
          <path d="M54 29v43l28 14V44l28-13v41L82 86" fill="white" />
          <path d="m62 43 12 6v21l-12-6Zm28 7 12-6v21l-12 6Z" fill="#f9ead5" />
          <path d="m22 68 15-7 16 7-15 8Z" fill="white" />
          <path d="M22 68v8l16 8 15-8v-8M38 76v8" />
          <path d="m111 68 15-7 16 7-15 8Z" fill="white" />
          <path d="M111 68v8l16 8 15-8v-8M127 76v8" />
          <path
            d="m35 57 7-3m-3-3 3 3-3 4m78-1 7-3m-3-3 3 3-3 4"
            stroke="#d9a45f"
          />
        </g>
      ) : kind === "trigger" ? (
        <g stroke={color} strokeWidth="1.6">
          <path d="m81 14-25 39 19 1-8 34 34-46-21 1 13-29Z" fill="#eee7ff" />
        </g>
      ) : (
        <g stroke={color} strokeWidth="1.5" strokeLinejoin="round">
          <path d="m38 27 65-15 22 12-63 17Z" fill="#f4edff" />
          <path d="M38 27v41l65-15V12M103 12l22 12v41l-22-12" fill="white" />
          <path d="m44 34 53-12v25L44 60Z" fill="#f1edfa" />
          <path d="m49 38 16-4v13l-16 4Zm23-5 19-4m-19 11 19-4m-19 11 12-3" />
          <path d="m78 64 11-3v14l15 7-27 9-16-8 17-6Z" fill="#f4edff" />
          <path d="m32 78 14-5 13 6-14 5Z" fill="white" />
        </g>
      )}
    </svg>
  );
}
