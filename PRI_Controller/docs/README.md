# PRI Controller Extension Usage

How to use **PRI Controller**: an Isaac Sim extension that applies Behavior Scripts to USD using MCC JSON.

## Enabling the Extension

### Option 1: Extension inside your project

If the `PRI_Controller` folder is under your project root (e.g. `PRI_Isaacsim_controller_v1.1`), Isaac Sim may load it automatically when run from that project (depends on Isaac Sim / Kit extension search path).

### Option 2: Load via ext folder

Specify the folder containing the extension when launching Isaac Sim.

```bash
# Example: use project root as ext folder
isaac-sim.sh --ext-folder /path/to/PRI_Isaacsim_controller_v1.1 --enable PRI_Controller
```

Windows example:

```cmd
python.exe path\to\isaac-sim\python.sh --ext-folder G:\...\PRI_Isaacsim_controller_v1.1 --enable PRI_Controller
```

- `--ext-folder`: **Project root** path (must contain the `PRI_Controller` folder).
- `--enable`: Extension package name; must match the name in `PRI_Controller/config/extension.toml` under `[package]`.

### Option 3: Enable manually from Window -> Extensions

After Isaac Sim starts, open **Window → Extensions**, find **PRI_Controller**, enable it; the toolbar menu will appear.

## Using the Extension

1. **Select "PRI Controller" from the toolbar/menu**
   The PRI Controller panel opens.

2. **Check project path**
   See if **Project Path** shows your project root.
   If it shows `(Not found)`, click **Refresh**.
   The extension treats the parent of the folder containing `scripts/config.json` as the project root.

3. **Buttons**
   - **1. Update Control Files**
     Updates `_target_prim_paths` etc. in the Control folder from MCC JSON.
     No need to open a USD file.
   - **2. Apply Behavior Scripts**
     First open the USD file specified in `config.json` as `usd_file` via **File → Open**.
     Then click this button to apply scripts and Axis/IO attributes to the open stage.
   - **3. Apply All**
     Runs 1 then 2. Open the USD before using step 2.

4. **Output Log**
   Script and extension messages appear here.
   If errors occur, check the log and `scripts/config.json` settings.

## Requirements

- **scripts/config.json** must exist under the project root.
- Set `paths`, `files`, `usd` etc. in **config.json** to match your folders, files, and USD.
- For **2. Apply Behavior Scripts**, open the target USD in Isaac Sim first.

For full project layout, Control/Scripts roles, and **config.json** field descriptions, see **PRI_Controller/README.md** (parent folder).

### Contact: jim2ning@gmail.com

