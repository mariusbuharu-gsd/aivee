import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RuleSparkline } from './RuleSparkline';

describe('RuleSparkline', () => {
  it('draws one thin bar per day and reads the total aloud', () => {
    render(<RuleSparkline perDay={[1, 0, 3, 2, 0, 4, 2]} />);
    const chart = screen.getByRole('img', { name: '12 alerte în ultimele 7 zile' });
    expect(chart.querySelectorAll('rect')).toHaveLength(7);
    expect(screen.getByText('12 alerte')).toBeInTheDocument();
  });

  it('speaks Romanian for one, for none and for twenty or more', () => {
    const { rerender } = render(<RuleSparkline perDay={[0, 0, 0, 0, 0, 0, 1]} />);
    expect(screen.getByRole('img', { name: '1 alertă în ultimele 7 zile' })).toBeInTheDocument();
    rerender(<RuleSparkline perDay={[0, 0, 0, 0, 0, 0, 0]} />);
    expect(
      screen.getByRole('img', { name: 'nicio alertă în ultimele 7 zile' }),
    ).toBeInTheDocument();
    rerender(<RuleSparkline perDay={[20, 0, 0, 0, 0, 0, 1]} />);
    expect(
      screen.getByRole('img', { name: '21 de alerte în ultimele 7 zile' }),
    ).toBeInTheDocument();
  });
});
