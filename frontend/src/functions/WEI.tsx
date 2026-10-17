import { Board } from "./Board";
import { WEI as DEF } from "./boards";
import type { FunctionProps } from "./registry";

export default function WEI(props: FunctionProps) {
  return <Board {...props} def={DEF} />;
}
