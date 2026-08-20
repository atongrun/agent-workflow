fn main() {
    if let Err(err) = runtime_v2_rust::main_entry() {
        eprintln!("{err}");
        std::process::exit(1);
    }
}
