import type { ReactNode } from 'react';

/** Resource identity keeps its visual consistent across pages, filters, and previews. */
export function ResourceVisual({
  resourceKey,
  className,
  children,
}: {
  resourceKey: string;
  className: string;
  children?: ReactNode;
}) {
  const variant =
    [...resourceKey].reduce((value, character) => value + character.charCodeAt(0), 0) % 4;
  return (
    <span className={`${className} resource-art-${variant}`}>
      <svg className="resource-pattern" viewBox="0 0 320 170" aria-hidden="true" focusable="false">
        <g fill="none" stroke="currentColor" strokeWidth="1.25">
          {variant === 0 ? (
            <>
              {[0, 1, 2, 3].map((index) => (
                <ellipse
                  key={index}
                  cx="160"
                  cy="85"
                  rx={36 + index * 15}
                  ry={36 + index * 7}
                  transform={`rotate(${index * 24} 160 85)`}
                />
              ))}
              <circle cx="160" cy="85" r="8" fill="currentColor" />
            </>
          ) : variant === 1 ? (
            <>
              {[0, 1, 2, 3, 4].map((index) => (
                <path
                  key={index}
                  d={`M${75 + index * 17} 123 ${118 + index * 14} 44 ${161 + index * 17} 123Z`}
                />
              ))}
            </>
          ) : variant === 2 ? (
            <>
              {[0, 1, 2, 3, 4].map((index) => (
                <rect
                  key={index}
                  x={108 + index * 9}
                  y={34 + index * 7}
                  width="70"
                  height="70"
                  rx="8"
                  transform="rotate(-18 160 85)"
                />
              ))}
            </>
          ) : (
            <>
              {[0, 1, 2, 3, 4, 5].map((index) => (
                <circle key={index} cx={105 + index * 20} cy="85" r="33" />
              ))}
            </>
          )}
        </g>
      </svg>
      {children}
    </span>
  );
}
