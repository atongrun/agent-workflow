package hostinstall

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"runtime"
)

// Run exposes only read-only planning and diagnosis. There is no install command.
func Run(args []string, out io.Writer) error {
	if len(args) == 0 || (args[0] != "plan" && args[0] != "doctor") {
		return errors.New("usage: awf host-install plan|doctor --manifest FILE [--json]")
	}
	f := flag.NewFlagSet("host-install", flag.ContinueOnError)
	f.SetOutput(out)
	file := f.String("manifest", "", "explicit locally reviewed Linux Host manifest")
	asJSON := f.Bool("json", false, "print a read-only plan as JSON")
	if err := f.Parse(args[1:]); err != nil {
		return err
	}
	if *file == "" || f.NArg() != 0 {
		return errors.New("read-only planning requires an explicit local manifest")
	}
	if runtime.GOOS != "linux" {
		return errors.New("this slice plans Linux Host only")
	}
	input, err := os.Open(*file)
	if err != nil {
		return errors.New("manifest is unreadable")
	}
	defer input.Close()
	data, err := io.ReadAll(io.LimitReader(input, MaxManifestBytes+1))
	if err != nil {
		return errors.New("manifest could not be read")
	}
	m, err := ParseManifest(data)
	if err != nil {
		return err
	}
	e := ObserveEnvironment()
	var p Plan
	if args[0] == "doctor" {
		p, err = Doctor(m, e)
	} else {
		p, err = BuildPlan(m, e)
	}
	if err != nil {
		return err
	}
	if *asJSON {
		return json.NewEncoder(out).Encode(p)
	}
	fmt.Fprintln(out, "AWF Linux Host: read-only plan; no installation, credentials or services changed.")
	for _, finding := range p.Findings {
		fmt.Fprintf(out, "%s: %s %q\n", finding.Check, finding.Status, finding.Detail)
	}
	for _, component := range p.Components {
		fmt.Fprintf(out, "component %s %s: download/verify/stage planned, not performed\n", component.ID, component.Version)
	}
	fmt.Fprintln(out, "Actual initialization, model selection and native acceptance remain required. No one-line installer is published.")
	return nil
}
